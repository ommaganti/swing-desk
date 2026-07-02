import numpy as np
from scipy.stats import norm

from swingdesk.greeks import bs_d1_d2, bs_delta, bs_gamma, year_fraction


def test_bs_gamma_matches_closed_form():
    S, K, T, r, q, sigma = 100.0, 100.0, 30 / 365, 0.04, 0.0, 0.30
    d1, _ = bs_d1_d2(np.array(S), np.array(K), np.array(T), r, q, np.array(sigma))
    expected = np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))
    assert np.isclose(float(bs_gamma(S, K, T, r, q, sigma)), float(expected))


def test_bs_gamma_degenerate_is_zero():
    assert float(bs_gamma(100, 100, 0.0, 0.04, 0.0, 0.30)) == 0.0   # T=0
    assert float(bs_gamma(100, 100, 0.1, 0.04, 0.0, 0.0)) == 0.0    # sigma=0


def test_bs_gamma_is_right_agnostic_and_positive():
    g = bs_gamma(np.array([90.0, 100.0, 110.0]), 100.0, 0.1, 0.04, 0.0, 0.3)
    assert (g > 0).all()


def test_delta_bounds_and_parity():
    S, K, T, r, q, sig = 100.0, 100.0, 0.1, 0.04, 0.0, 0.30
    dc = float(bs_delta(S, K, T, r, q, sig, "C"))
    dp = float(bs_delta(S, K, T, r, q, sig, "P"))
    assert 0.0 < dc < 1.0
    assert -1.0 < dp < 0.0
    # call delta - put delta = exp(-qT)
    assert np.isclose(dc - dp, np.exp(-q * T), atol=1e-9)


def test_year_fraction():
    assert np.isclose(year_fraction(365), 1.0)
    assert year_fraction(0) > 0  # never zero -> avoids div-by-zero downstream
