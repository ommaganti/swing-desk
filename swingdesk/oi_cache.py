"""Pre-market open-interest cache (free, no extra data vendor).

Open interest is a once-daily figure (OCC settles it overnight) — it does not
change intraday. yfinance only *delivers* OI while the US session is live and
returns 0 off-hours, which empties the GEX layer pre-market.

This cache closes that gap with zero new API keys: whenever a chain pull has
live OI (market hours), we snapshot the whole chain per symbol; when a later
pull comes back zeroed (pre-market), we serve that last-good chain with the
current spot, labelled "OI as of <capture time>". Since OI barely moves day to
day, the at-most ~1-session staleness is fine for multi-day swing decisions.

Demo/synthetic chains are never cached or served, so demo data can't leak into
a live read. A keyed provider that returns real off-hours OI (e.g. Tradier)
simply never triggers the fallback.
"""
from __future__ import annotations

import os
import pickle
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import DATA_DIR
from .models import ExpiryChain, OptionChain

CACHE_DIR = DATA_DIR / "oi_cache"


def _path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol.upper()}.pkl"


def _is_synthetic(chain: OptionChain) -> bool:
    s = (chain.source or "").lower()
    return "synthetic" in s or "demo" in s


def total_oi(chain: OptionChain) -> float:
    tot = 0.0
    for ec in chain.by_expiry.values():
        for df in (ec.calls, ec.puts):
            if df is not None and "openInterest" in df.columns and not df.empty:
                tot += float(pd.to_numeric(df["openInterest"], errors="coerce").fillna(0).sum())
    return tot


def _capture(chain: OptionChain) -> str:
    """Snapshot a live chain per symbol. Returns the pretty capture timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    tmp = _path(chain.symbol).with_suffix(".pkl.tmp")
    with open(tmp, "wb") as fh:
        pickle.dump({"chain": chain, "captured_at": captured_at}, fh)
    os.replace(tmp, _path(chain.symbol))  # atomic
    return captured_at


def _load(symbol: str):
    p = _path(symbol)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            d = pickle.load(fh)
        return d["chain"], d["captured_at"]
    except Exception:
        return None


def serve_oi(chain: OptionChain, live_spot: Optional[float]) -> tuple[OptionChain, Optional[str]]:
    """Return (chain_to_use, oi_as_of).

    oi_as_of is "live" when the live pull had OI (and was cached), a capture
    timestamp when the chain was backfilled from cache, or None when neither
    live OI nor a cache entry was available.
    """
    if _is_synthetic(chain):
        return chain, None  # never cache or serve demo data

    if total_oi(chain) > 0:
        return chain, "live" if _safe_capture(chain) else "live"

    cached = _load(chain.symbol)
    if cached is None:
        return chain, None
    snap, captured_at = cached

    today = date.today()
    by: dict[date, ExpiryChain] = {}
    for exp, ec in snap.by_expiry.items():
        dte = (exp - today).days
        if dte < 0:
            continue  # drop expiries that have rolled off since capture
        by[exp] = ExpiryChain(expiry=exp, dte=dte, calls=ec.calls, puts=ec.puts)
    if not by:
        return chain, None

    spot = live_spot or snap.spot
    rebuilt = OptionChain(
        symbol=chain.symbol, spot=spot, as_of=datetime.now(timezone.utc),
        source=f"{snap.source} [OI cached {captured_at}]", is_delayed=True, by_expiry=by,
    )
    return rebuilt, captured_at


def _safe_capture(chain: OptionChain) -> bool:
    try:
        _capture(chain)
        return True
    except Exception:
        return False
