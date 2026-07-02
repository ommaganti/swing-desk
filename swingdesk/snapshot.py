"""Daily snapshot — the 'pull every morning' engine.

Each morning (launchd → refresh.py) this precomputes the funnel for the whole
watchlist and re-reads every OPEN journal position (current price, unrealized
move, and a fresh GEX regime read — gamma rolls off at OPEX and the regime can
flip). The result is pickled to data/snapshots/ so the dashboard's morning view
is instant and stamped with an honest 'as of' time instead of re-pulling on
every page load.

A small JSON sidecar (latest.json) makes the snapshot state human-readable.
"""
from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import journal
from .analysis import analyze, compute_index_gex
from .config import DATA_DIR, BookRules, load_book_rules
from .gex import compute_gex_profile
from .models import FunnelResult

SNAP_DIR = DATA_DIR / "snapshots"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
LATEST_PKL = SNAP_DIR / "latest.pkl"
LATEST_JSON = SNAP_DIR / "latest.json"

DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "SPY", "QQQ"]


# --------------------------------------------------------------------------- #
# Watchlist                                                                     #
# --------------------------------------------------------------------------- #
def load_watchlist() -> list[str]:
    try:
        with open(WATCHLIST_FILE) as fh:
            data = json.load(fh)
        tickers = [t.strip().upper() for t in data.get("tickers", []) if str(t).strip()]
        return tickers or list(DEFAULT_WATCHLIST)
    except (FileNotFoundError, json.JSONDecodeError):
        return list(DEFAULT_WATCHLIST)


def save_watchlist(tickers: list[str]) -> None:
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    clean = [t.strip().upper() for t in tickers if str(t).strip()]
    with open(WATCHLIST_FILE, "w") as fh:
        json.dump({"tickers": clean}, fh, indent=2)


# --------------------------------------------------------------------------- #
# Models                                                                        #
# --------------------------------------------------------------------------- #
@dataclass
class PositionUpdate:
    trade_id: int
    ticker: str
    direction: str
    instrument: str
    entry: float
    stop: float
    target: float
    size: float
    risk_dollars: Optional[float]
    regime_at_entry: Optional[str]
    current_price: Optional[float] = None
    unrealized_move: Optional[float] = None        # signed by direction, price terms
    unrealized_dollars: Optional[float] = None     # shares only; options need repricing
    dist_to_target_pct: Optional[float] = None
    dist_to_stop_pct: Optional[float] = None
    current_regime: Optional[str] = None
    regime_flipped: bool = False
    note: str = ""


@dataclass
class Snapshot:
    created_at: datetime
    book_size: float
    risk_pct: float
    watchlist: list[str]
    results: dict = field(default_factory=dict)     # ticker -> FunnelResult
    errors: dict = field(default_factory=dict)      # ticker -> error string
    positions: list = field(default_factory=list)   # list[PositionUpdate]
    demo: bool = False

    @property
    def as_of(self) -> str:
        return self.created_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")

    @property
    def age_hours(self) -> float:
        return (datetime.now(timezone.utc) - self.created_at).total_seconds() / 3600.0


# --------------------------------------------------------------------------- #
# Build / persist / load                                                        #
# --------------------------------------------------------------------------- #
def update_open_positions(providers, book: BookRules) -> list[PositionUpdate]:
    """Re-read every OPEN journal trade: current price, unrealized move, fresh regime."""
    df = journal.list_trades()
    if df.empty:
        return []
    open_df = df[df["outcome"].fillna("open") == "open"]
    out: list[PositionUpdate] = []
    for row in open_df.itertuples():
        direction = (getattr(row, "direction", None) or "long")
        entry = _f(getattr(row, "entry", None))
        stop = _f(getattr(row, "stop", None))
        target = _f(getattr(row, "target", None))
        size = _f(getattr(row, "size", None)) or 0.0
        instrument = getattr(row, "instrument", None) or "shares"
        pu = PositionUpdate(
            trade_id=int(row.id), ticker=str(row.ticker), direction=direction,
            instrument=instrument, entry=entry or 0.0, stop=stop or 0.0,
            target=target or 0.0, size=size, risk_dollars=_f(getattr(row, "risk_dollars", None)),
            regime_at_entry=getattr(row, "regime_tag", None),
        )
        try:
            pu.current_price = providers.quotes.get_quote(pu.ticker).price
        except Exception as e:
            pu.note = f"quote unavailable ({type(e).__name__})"
        try:
            chain = providers.options.get_chain(pu.ticker, max_expiries=3)
            pu.current_regime = compute_gex_profile(chain).regime
        except Exception:
            pu.current_regime = None

        cur, e = pu.current_price, pu.entry
        if cur and e:
            move = (cur - e) if direction == "long" else (e - cur)
            pu.unrealized_move = move
            if instrument == "shares":
                pu.unrealized_dollars = move * size
            else:
                pu.note = (pu.note + "; " if pu.note else "") + "option P/L needs repricing"
            if pu.target:
                pu.dist_to_target_pct = (pu.target - cur) / cur * 100
            if pu.stop:
                pu.dist_to_stop_pct = (cur - pu.stop) / cur * 100
        pu.regime_flipped = bool(
            pu.current_regime and pu.regime_at_entry
            and pu.current_regime != pu.regime_at_entry
            and pu.regime_at_entry in ("positive", "negative")
        )
        out.append(pu)
    return out


def build_snapshot(providers, watchlist: list[str], book: BookRules, demo: bool = False,
                   max_workers: int = 6, max_expiries: int = 3) -> Snapshot:
    results: dict[str, FunnelResult] = {}
    errors: dict[str, str] = {}

    # Precompute the index-GEX backdrop once (it is cached per day) so the parallel
    # workers neither each pull the heavy SPY chain nor race to fill the cache.
    try:
        compute_index_gex(providers)
    except Exception:
        pass

    def _one(tkr: str):
        # Morning scan uses a neutral default "long" bias just to populate the
        # cards; the user sets the real bias in the Analyze tab before sizing.
        return analyze(tkr, "long", providers, book, hold_days=10, max_expiries=max_expiries)

    # yfinance/Tradier calls are I/O-bound (network) so threads give a near-linear
    # speedup; keep the pool modest to avoid tripping provider rate limits.
    workers = max(1, min(max_workers, len(watchlist)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_one, t): t for t in watchlist}
        for fut in as_completed(futs):
            tkr = futs[fut]
            try:
                results[tkr] = fut.result()
            except Exception as e:  # noqa: BLE001 — one bad ticker must not abort the run
                errors[tkr] = f"{type(e).__name__}: {e}"
    positions = update_open_positions(providers, book)
    return Snapshot(
        created_at=datetime.now(timezone.utc), book_size=book.book_size,
        risk_pct=book.default_risk_pct, watchlist=list(watchlist),
        results=results, errors=errors, positions=positions, demo=demo,
    )


def save_snapshot(snap: Snapshot) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    date_str = snap.created_at.astimezone().strftime("%Y-%m-%d")
    with open(SNAP_DIR / f"{date_str}.pkl", "wb") as fh:
        pickle.dump(snap, fh)
    with open(LATEST_PKL, "wb") as fh:
        pickle.dump(snap, fh)
    summary = {
        "created_at": snap.created_at.isoformat(),
        "as_of": snap.as_of,
        "demo": snap.demo,
        "book_size": snap.book_size,
        "risk_pct": snap.risk_pct,
        "watchlist": snap.watchlist,
        "tickers_ok": list(snap.results),
        "errors": snap.errors,
        "n_positions": len(snap.positions),
    }
    with open(LATEST_JSON, "w") as fh:
        json.dump(summary, fh, indent=2, default=str)


def load_latest() -> Optional[Snapshot]:
    if not LATEST_PKL.exists():
        return None
    try:
        with open(LATEST_PKL, "rb") as fh:
            return pickle.load(fh)
    except Exception:
        return None


def run_refresh(demo: Optional[bool] = None) -> Snapshot:
    """Top-level: build providers, pull the watchlist + positions, save a snapshot."""
    if demo is None:
        demo = os.getenv("SWINGDESK_DEMO", "").strip() in ("1", "true", "True")
    book = load_book_rules()
    if demo:
        from .providers import build_demo_providers
        providers = build_demo_providers()
    else:
        from .providers import build_providers
        providers = build_providers()
    watchlist = load_watchlist()
    snap = build_snapshot(providers, watchlist, book, demo=demo)
    save_snapshot(snap)
    return snap


def _f(x) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None
