"""Local GEX on a hand-computed synthetic chain (gamma supplied to be exact).

With spot=100, the factor 100*spot**2*0.01 = 10_000, so gex_i = gamma*oi*10_000.
"""
import pandas as pd
from pytest import approx

from swingdesk.gex import find_gamma_flip, find_walls, gex_by_strike


def _frame(strikes, oi, gamma):
    return pd.DataFrame({
        "strike": strikes, "openInterest": oi, "gamma": gamma,
        "impliedVolatility": [0.3] * len(strikes),
        "bid": [1.0] * len(strikes), "ask": [1.1] * len(strikes),
        "lastPrice": [1.05] * len(strikes), "volume": [1] * len(strikes),
    })


def _profile():
    spot = 100.0
    calls = _frame([95, 100, 105], [10, 20, 30], [0.01, 0.02, 0.03])
    puts = _frame([95, 100, 105], [40, 10, 5], [0.02, 0.02, 0.01])
    return spot, gex_by_strike(spot, calls, puts, T=0.1)


def test_per_strike_and_net_gex():
    spot, bs = _profile()
    # call_gex = gamma*oi*10000 ; put_gex likewise
    by = bs.set_index("strike")
    assert by.loc[105, "call_gex"] == approx(9000.0)   # 0.03*30*10000
    assert by.loc[95, "put_gex"] == approx(8000.0)     # 0.02*40*10000
    assert by.loc[95, "net_gex"] == approx(-7000.0)
    assert bs["net_gex"].sum() == approx(3500.0)       # positive overall


def test_walls():
    spot, bs = _profile()
    call_wall, put_wall = find_walls(bs, spot)
    assert call_wall == 105.0   # largest call gamma above spot
    assert put_wall == 95.0     # largest put gamma below spot


def test_gamma_flip_interpolates_zero_crossing():
    spot, bs = _profile()
    flip = find_gamma_flip(bs)
    # cum crosses zero between 100 (-5000) and 105 (+3500): 100 + 5000*5/8500
    assert abs(flip - (100 + 5000 * 5 / 8500)) < 1e-6
