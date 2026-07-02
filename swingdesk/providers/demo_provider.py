"""Synthetic 'demo data' providers.

Why this exists: free delayed feeds (yfinance) frequently return option chains
with ZEROED open interest / bid-ask outside of (or at odd) market hours, which
makes the GEX layer empty through no fault of the math. Demo mode supplies a
realistic, self-consistent liquid chain so the full dashboard (regime, walls,
IV, option sizing) can be explored offline and verified deterministically.

Everything here is CLEARLY SYNTHETIC and labeled as such in the UI. It exercises
the real local-GEX path (gamma is derived from IV via Black-Scholes, not faked).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
from scipy.stats import norm

from ..models import Catalyst, ExpiryChain, Fundamentals, OptionChain, Quote
from .registry import Providers

_SPOT = 100.0
_SYMBOL = "DEMO"
_R = 0.043


def _bs_price(S, K, T, sigma, right):
    if T <= 0 or sigma <= 0:
        return max((S - K) if right == "C" else (K - S), 0.0)
    d1 = (math.log(S / K) + (_R + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if right == "C":
        return S * norm.cdf(d1) - K * math.exp(-_R * T) * norm.cdf(d2)
    return K * math.exp(-_R * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _smile(K, extra=0.0):
    # Downside skew + mild convexity; OTM puts richer than OTM calls.
    iv = 0.28 + 0.0020 * (_SPOT - K) + 0.00005 * (K - _SPOT) ** 2 + extra
    return float(min(max(iv, 0.15), 0.90))


def _expiry_frame(dte, iv_extra):
    T = dte / 365.0
    strikes = np.arange(70.0, 130.1, 2.5)
    rows_c, rows_p = [], []
    for K in strikes:
        iv = _smile(K, iv_extra)
        # Call OI weighted above spot, put OI below. Net-positive (range) regime
        # with a gamma flip just below spot where the cumulative curve crosses zero.
        call_oi = int(12000 * math.exp(-((K - 105) / 9) ** 2)
                      + 1000 * math.exp(-((K - _SPOT) / 15) ** 2) + 400)
        put_oi = int(7000 * math.exp(-((K - 93) / 8) ** 2)
                     + 1000 * math.exp(-((K - _SPOT) / 15) ** 2) + 400)
        # New-positioning hotspots: volume >> OI at the 105 call and 90 put.
        call_vol = int(call_oi * (1.6 if abs(K - 105) < 1.3 else 0.4))
        put_vol = int(put_oi * (1.7 if abs(K - 90) < 1.3 else 0.4))
        cpx = _bs_price(_SPOT, K, T, iv, "C")
        ppx = _bs_price(_SPOT, K, T, iv, "P")
        rows_c.append((K, round(cpx - 0.05, 2), round(cpx + 0.05, 2), round(cpx, 2), call_vol, call_oi, iv))
        rows_p.append((K, round(ppx - 0.05, 2), round(ppx + 0.05, 2), round(ppx, 2), put_vol, put_oi, iv))
    cols = ["strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"]
    calls = pd.DataFrame(rows_c, columns=cols)
    puts = pd.DataFrame(rows_p, columns=cols)
    calls[["bid", "ask"]] = calls[["bid", "ask"]].clip(lower=0.01)
    puts[["bid", "ask"]] = puts[["bid", "ask"]].clip(lower=0.01)
    return ExpiryChain(expiry=date.today() + timedelta(days=dte), dte=dte, calls=calls, puts=puts)


class _DemoQuotes:
    def get_quote(self, symbol):
        return Quote(symbol, _SPOT, datetime.now(tz=timezone.utc),
                     "DEMO (synthetic)", is_delayed=False, typical_delay_min=0)


class _DemoFundamentals:
    def get_fundamentals(self, symbol):
        return Fundamentals(symbol, "DEMO (synthetic)", ps_ttm=8.0,
                            revenue_growth_pct=22.0, market_cap=1.5e12,
                            sector="Technology", analyst_high=130, analyst_low=80,
                            analyst_mean=112)


class _DemoOptions:
    def get_chain(self, symbol, max_expiries=4):
        # Front IV slightly above back -> +term structure (crush risk) for the demo.
        front = _expiry_frame(7, iv_extra=0.02)
        back = _expiry_frame(35, iv_extra=0.0)
        by = {front.expiry: front, back.expiry: back}
        return OptionChain(symbol, _SPOT, datetime.now(tz=timezone.utc),
                           "DEMO (synthetic)", is_delayed=False, by_expiry=by)


class _DemoCatalysts:
    def get_catalysts(self, symbol, lookback_days=14):
        return [
            Catalyst("partnership", f"{symbol} announces partnership with a major cloud vendor",
                     source="DEMO", when=date.today() - timedelta(days=2), dated=False, binary=False),
            Catalyst("news", f"{symbol} product launch well received by reviewers",
                     source="DEMO", when=date.today() - timedelta(days=5), dated=False, binary=False),
        ]

    def get_next_earnings(self, symbol):
        return date.today() + timedelta(days=21)  # outside a default 10d hold


def build_demo_providers() -> Providers:
    return Providers(
        quotes=_DemoQuotes(), fundamentals=_DemoFundamentals(), options=_DemoOptions(),
        catalysts=_DemoCatalysts(), gex_provider=None,
        catalyst_source="DEMO (synthetic)", gex_cross_check_source=None,
        options_source="DEMO (synthetic)",
    )
