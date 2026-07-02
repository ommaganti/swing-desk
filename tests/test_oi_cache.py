from datetime import date, datetime, timezone

import pandas as pd

from swingdesk import oi_cache
from swingdesk.models import ExpiryChain, OptionChain


def _chain(symbol, spot, oi, source="yfinance"):
    strikes = [90, 95, 100, 105, 110]

    def side():
        return pd.DataFrame({
            "strike": strikes, "bid": [1.0] * 5, "ask": [1.1] * 5, "lastPrice": [1.05] * 5,
            "volume": [10] * 5, "openInterest": [oi] * 5, "impliedVolatility": [0.3] * 5,
        })

    exp = date(2026, 12, 18)
    ec = ExpiryChain(exp, (exp - date.today()).days, side(), side())
    return OptionChain(symbol, spot, datetime.now(timezone.utc), source, True, {exp: ec})


def test_capture_then_backfill(tmp_path, monkeypatch):
    monkeypatch.setattr(oi_cache, "CACHE_DIR", tmp_path)
    # 1) A live chain WITH open interest is captured and returned as "live".
    served, asof = oi_cache.serve_oi(_chain("ZZZ", 100.0, 5000), 100.0)
    assert asof == "live"
    assert oi_cache.total_oi(served) > 0

    # 2) A zeroed (pre-market) chain is backfilled from the cache.
    served2, asof2 = oi_cache.serve_oi(_chain("ZZZ", 101.0, 0), 101.0)
    assert asof2 not in (None, "live")        # a capture timestamp
    assert oi_cache.total_oi(served2) > 0     # OI restored from cache
    assert served2.spot == 101.0             # uses the live spot, not the cached one


def test_demo_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(oi_cache, "CACHE_DIR", tmp_path)
    served, asof = oi_cache.serve_oi(_chain("DDD", 100.0, 9000, source="DEMO (synthetic)"), 100.0)
    assert asof is None
    assert not list(tmp_path.glob("*.pkl"))   # nothing written for synthetic data


def test_no_cache_yet_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(oi_cache, "CACHE_DIR", tmp_path)
    served, asof = oi_cache.serve_oi(_chain("NEW", 100.0, 0), 100.0)
    assert asof is None
    assert oi_cache.total_oi(served) == 0     # no cache to backfill from
