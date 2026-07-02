"""Black-Scholes greeks for local GEX, mirroring vol_surface/pricing.py conventions.

Conventions (identical to the workspace's vol_surface package so results are
comparable):
  S spot, K strike, T year-fraction to expiry (ACT/365), sigma annual vol,
  r continuously-compounded risk-free rate, q continuous dividend yield,
  right "C"/"P". All functions are vectorized over numpy arrays.

yfinance option chains do NOT ship greeks, so we derive gamma/delta from the
chain's implied-vol column here. When a provider supplies native greeks
(e.g. Tradier/ORATS), the GEX layer uses those instead and these are unused.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

from .models import Right


def bs_d1_d2(
    S: np.ndarray, K: np.ndarray, T: np.ndarray, r: float, q: float, sigma: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """d1, d2 of Black-Scholes. Caller guards against T<=0 / sigma<=0."""
    sig_sqrt_t = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / sig_sqrt_t
    d2 = d1 - sig_sqrt_t
    return d1, d2


def bs_gamma(S, K, T, r: float, q: float, sigma) -> np.ndarray:
    """Gamma = exp(-qT) * phi(d1) / (S * sigma * sqrt(T)).

    Gamma is identical for calls and puts. Degenerate inputs (T<=0 or sigma<=0)
    return 0.0 rather than NaN/inf, so a single bad row cannot poison a sum.
    """
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1, _ = bs_d1_d2(S, K, T, r, q, sigma)
        gamma = np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))
    gamma = np.where((T <= 0) | (sigma <= 0) | ~np.isfinite(gamma), 0.0, gamma)
    return gamma


def bs_delta(S, K, T, r: float, q: float, sigma, right: Right) -> np.ndarray:
    """Delta. Call delta in [0,1], put delta in [-1,0]. Degenerate -> intrinsic sign."""
    S = np.asarray(S, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1, _ = bs_d1_d2(S, K, T, r, q, sigma)
        disc_q = np.exp(-q * T)
        if right == "C":
            delta = disc_q * norm.cdf(d1)
        else:
            delta = -disc_q * norm.cdf(-d1)
    # Degenerate: in-the-money -> +/-1, out -> 0 (sign by right).
    if right == "C":
        deg = np.where(S > K, 1.0, 0.0)
    else:
        deg = np.where(S < K, -1.0, 0.0)
    delta = np.where((T <= 0) | (sigma <= 0) | ~np.isfinite(delta), deg, delta)
    return delta


def year_fraction(dte: int) -> float:
    """ACT/365 year fraction from integer days-to-expiry, floored at ~intraday."""
    return max(dte, 0) / 365.0 if dte > 0 else (1.0 / 365.0)
