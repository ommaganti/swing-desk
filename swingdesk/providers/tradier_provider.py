"""Tradier options provider — real open interest + native greeks (free with account).

Tradier's `/markets/options/chains?greeks=true` returns bid/ask/last/volume/
open_interest plus delta/gamma/theta/vega and IV (via ORATS) for every strike.
Because gamma is NATIVE here, the local GEX engine uses it directly (gex.py reads
the `gamma` column when present) instead of Black-Scholes-from-IV — so GEX is
built on real OI × real gamma, which fixes the zeroed-OI problem yfinance has
outside market hours.

Needs TRADIER_API_KEY. Set TRADIER_BASE_URL to the sandbox host for paper/delayed
data; set TRADIER_REALTIME=1 if your account has real-time market data. Fails
soft (returns an empty/partial chain) so a Tradier hiccup degrades to share-only
for that ticker rather than crashing the funnel.

Docs: https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import get_key
from ..models import ExpiryChain, OptionChain
from .base import OptionsProvider

_PROD = "https://api.tradier.com/v1"
_COLS = ["strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility", "gamma"]


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _num(x) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


class TradierOptionsProvider(OptionsProvider):
    source = "Tradier (ORATS greeks)"

    def __init__(self) -> None:
        self._key = get_key("tradier")
        if not self._key:
            raise RuntimeError("TradierOptionsProvider requires TRADIER_API_KEY")
        self._base = os.getenv("TRADIER_BASE_URL", _PROD).rstrip("/")
        self._delayed = ("sandbox" in self._base) or os.getenv("TRADIER_REALTIME", "") != "1"
        self._s = _session()

    def _get(self, path: str, params: dict):
        try:
            r = self._s.get(
                f"{self._base}/{path}", params=params, timeout=12,
                headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            return None  # fail soft

    def _spot(self, symbol: str) -> float:
        d = self._get("markets/quotes", {"symbols": symbol})
        try:
            q = d["quotes"]["quote"]
            if isinstance(q, list):
                q = q[0]
            v = _num(q.get("last")) or _num(q.get("prevclose"))
            if v:
                return v
        except Exception:
            pass
        # Fall back to a yfinance spot so GEX isn't zeroed by a missing Tradier quote.
        try:
            import yfinance as yf
            return float(yf.Ticker(symbol).fast_info["last_price"])
        except Exception:
            return 0.0

    def _expirations(self, symbol: str) -> list[str]:
        d = self._get("markets/options/expirations", {"symbol": symbol, "includeAllRoots": "true"})
        try:
            return _as_list(d["expirations"]["date"])
        except Exception:
            return []

    @staticmethod
    def _frame(options: list, want_call: bool) -> pd.DataFrame:
        rows = []
        for o in options:
            if (str(o.get("option_type")) == "call") != want_call:
                continue
            g = o.get("greeks") or {}
            rows.append({
                "strike": _num(o.get("strike")),
                "bid": _num(o.get("bid")),
                "ask": _num(o.get("ask")),
                "lastPrice": _num(o.get("last")),
                "volume": _num(o.get("volume")) or 0,
                "openInterest": _num(o.get("open_interest")) or 0,
                "impliedVolatility": _num(g.get("mid_iv")) or _num(g.get("smv_vol")),
                "gamma": _num(g.get("gamma")),
            })
        return pd.DataFrame(rows, columns=_COLS).dropna(subset=["strike"]).reset_index(drop=True)

    def get_chain(self, symbol: str, max_expiries: int = 4) -> OptionChain:
        symbol = symbol.upper().strip()
        spot = self._spot(symbol)
        by_expiry: dict[date, ExpiryChain] = {}
        today = date.today()
        for es in self._expirations(symbol)[:max_expiries]:
            try:
                exp = date.fromisoformat(es)
            except (TypeError, ValueError):
                continue
            d = self._get("markets/options/chains",
                          {"symbol": symbol, "expiration": es, "greeks": "true"})
            try:
                opts = _as_list(d["options"]["option"])
            except Exception:
                opts = []
            if not opts:
                continue
            by_expiry[exp] = ExpiryChain(expiry=exp, dte=(exp - today).days,
                                         calls=self._frame(opts, True),
                                         puts=self._frame(opts, False))
        return OptionChain(symbol=symbol, spot=spot, as_of=datetime.now(tz=timezone.utc),
                           source=self.source, is_delayed=self._delayed, by_expiry=by_expiry)
