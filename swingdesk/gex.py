"""Local gamma-exposure (GEX) engine — the zero-key Phase-2 backbone.

Implements the spec formulas EXACTLY (standard dealer assumption: calls add
gamma, puts subtract it):

    gex_i      = gamma_i * oi_i * 100 * spot**2 * 0.01
    net_gex    = sum(gex_calls) - sum(gex_puts)
    regime     = positive if net_gex > 0 else negative
    gamma_flip = spot level where the cumulative GEX curve crosses zero
    call_wall  = strike with the largest positive gamma ABOVE spot
    put_wall   = strike with the largest (abs) gamma BELOW spot

Gamma comes from a provider's native greeks when present, else from
Black-Scholes on the chain's implied-vol column (greeks.bs_gamma).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .config import risk_free_rate
from .greeks import bs_gamma, year_fraction
from .models import GexProfile, OptionChain


def _gamma_for(df: pd.DataFrame, spot: float, T: float, r: float, q: float) -> np.ndarray:
    """Use a native `gamma` column if the provider supplied one, else Black-Scholes."""
    if "gamma" in df.columns:
        g = pd.to_numeric(df["gamma"], errors="coerce").to_numpy(dtype=float)
        if np.isfinite(g).any():
            return np.nan_to_num(g, nan=0.0)
    iv = pd.to_numeric(df["impliedVolatility"], errors="coerce").to_numpy(dtype=float)
    strike = pd.to_numeric(df["strike"], errors="coerce").to_numpy(dtype=float)
    return bs_gamma(spot, strike, T, r, q, iv)


def _strike_gex(df: pd.DataFrame, spot: float, T: float, r: float, q: float) -> pd.Series:
    """Per-strike GEX magnitude (>=0) for one side (calls OR puts), summed by strike."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    gamma = _gamma_for(df, spot, T, r, q)
    oi = pd.to_numeric(df["openInterest"], errors="coerce").fillna(0).to_numpy(dtype=float)
    strike = pd.to_numeric(df["strike"], errors="coerce").to_numpy(dtype=float)
    gex = gamma * oi * 100.0 * spot**2 * 0.01
    s = pd.Series(gex, index=strike).dropna()
    return s.groupby(level=0).sum()


def gex_by_strike(
    spot: float,
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    T: float,
    r: float = None,
    q: float = 0.0,
) -> pd.DataFrame:
    """Per-strike GEX for a single expiry.

    Returns columns: strike, call_gex (>=0), put_gex (>=0), net_gex
    (= call_gex - put_gex), cum_gex (running sum of net_gex by ascending strike).
    """
    r = risk_free_rate() if r is None else r
    c = _strike_gex(calls, spot, T, r, q).rename("call_gex")
    p = _strike_gex(puts, spot, T, r, q).rename("put_gex")
    df = pd.concat([c, p], axis=1).fillna(0.0)
    df.index.name = "strike"
    df = df.reset_index().sort_values("strike").reset_index(drop=True)
    df["net_gex"] = df["call_gex"] - df["put_gex"]
    df["cum_gex"] = df["net_gex"].cumsum()
    return df


def find_gamma_flip(by_strike: pd.DataFrame) -> Optional[float]:
    """Spot level where the cumulative GEX curve crosses zero (linear interp).

    Only a GENUINE interior sign change counts. Far-OTM strikes can have gamma
    that underflows to exactly 0, so a leading/trailing zero is NOT a flip — that
    would falsely plant the flip at the edge of the strike range. If the
    cumulative curve never changes sign, there is no flip (return None).
    """
    if by_strike.empty or len(by_strike) < 2:
        return None
    strikes = by_strike["strike"].to_numpy(dtype=float)
    cum = by_strike["cum_gex"].to_numpy(dtype=float)
    for i in range(1, len(cum)):
        y0, y1 = cum[i - 1], cum[i]
        if y0 * y1 < 0:  # straddles zero -> interpolate the crossing
            x0, x1 = strikes[i - 1], strikes[i]
            return float(x0 - y0 * (x1 - x0) / (y1 - y0))
        # An exact interior zero counts only if the sign actually flips around it.
        if y1 == 0.0 and 0 < i < len(cum) - 1 and y0 != 0.0 and cum[i + 1] != 0.0:
            if y0 * cum[i + 1] < 0:
                return float(strikes[i])
    return None


def find_walls(by_strike: pd.DataFrame, spot: float) -> tuple[Optional[float], Optional[float]]:
    """(call_wall, put_wall): largest call-gamma strike above spot, largest
    put-gamma strike below spot."""
    above = by_strike[by_strike["strike"] > spot]
    below = by_strike[by_strike["strike"] < spot]
    call_wall = None
    if not above.empty and above["call_gex"].max() > 0:
        call_wall = float(above.loc[above["call_gex"].idxmax(), "strike"])
    put_wall = None
    if not below.empty and below["put_gex"].max() > 0:
        put_wall = float(below.loc[below["put_gex"].idxmax(), "strike"])
    return call_wall, put_wall


def compute_gex_profile(
    chain: OptionChain,
    r: float = None,
    q: float = 0.0,
    max_expiries: Optional[int] = None,
    is_soft: bool = False,
    source: Optional[str] = None,
    note: str = "",
) -> GexProfile:
    """Aggregate GEX across (up to `max_expiries`) expiries into one profile."""
    r = risk_free_rate() if r is None else r
    spot = chain.spot
    expiries = chain.expiries
    if max_expiries is not None:
        expiries = expiries[:max_expiries]

    frames = []
    for exp in expiries:
        ec = chain.by_expiry[exp]
        T = year_fraction(ec.dte)
        frames.append(gex_by_strike(spot, ec.calls, ec.puts, T, r, q))

    empty_cols = ["strike", "call_gex", "put_gex", "net_gex", "cum_gex"]
    if not frames or all(f.empty for f in frames):
        return GexProfile(
            symbol=chain.symbol, spot=spot, net_gex=0.0, regime="positive",
            gamma_flip=None, call_wall=None, put_wall=None,
            by_strike=pd.DataFrame(columns=empty_cols),
            source=source or chain.source, is_delayed=chain.is_delayed,
            is_soft=is_soft, note=note or "no option data",
        )

    allf = pd.concat(frames, ignore_index=True)
    agg = allf.groupby("strike", as_index=False)[["call_gex", "put_gex"]].sum()
    agg = agg.sort_values("strike").reset_index(drop=True)
    agg["net_gex"] = agg["call_gex"] - agg["put_gex"]
    agg["cum_gex"] = agg["net_gex"].cumsum()

    net = float(agg["net_gex"].sum())
    regime = "positive" if net > 0 else "negative"
    flip = find_gamma_flip(agg)
    call_wall, put_wall = find_walls(agg, spot)

    return GexProfile(
        symbol=chain.symbol, spot=spot, net_gex=net, regime=regime,
        gamma_flip=flip, call_wall=call_wall, put_wall=put_wall, by_strike=agg,
        source=source or chain.source, is_delayed=chain.is_delayed,
        is_soft=is_soft, note=note,
    )
