"""Funnel logic with fake providers (no network)."""
from datetime import date, datetime, timezone

import pandas as pd

from swingdesk.analysis import analyze
from swingdesk.models import ExpiryChain, Fundamentals, OptionChain, Quote
from swingdesk.providers import Providers


def _chain(symbol, spot, oi, vol, spread):
    strikes = [spot * m for m in (0.9, 0.95, 1.0, 1.05, 1.1)]

    def side():
        mid = 2.0
        return pd.DataFrame({
            "strike": strikes, "bid": [mid - spread / 2] * 5, "ask": [mid + spread / 2] * 5,
            "lastPrice": [mid] * 5, "volume": [vol] * 5, "openInterest": [oi] * 5,
            "impliedVolatility": [0.35] * 5,
        })

    ec = ExpiryChain(date(2026, 12, 18), 30, side(), side())
    return OptionChain(symbol, spot, datetime.now(tz=timezone.utc), "synthetic", True, {ec.expiry: ec})


class _Q:
    def get_quote(self, s):
        return Quote(s, 100.0, datetime.now(tz=timezone.utc), "fake")


class _F:
    def __init__(self, mcap):
        self.mcap = mcap

    def get_fundamentals(self, s):
        return Fundamentals(s, "fake", ps_ttm=5.0, revenue_growth_pct=20.0,
                            market_cap=self.mcap, sector="Technology",
                            analyst_high=130, analyst_low=90, analyst_mean=110)


class _O:
    def __init__(self, oi, vol, spread):
        self.oi, self.vol, self.spread = oi, vol, spread

    def get_chain(self, s, max_expiries=4):
        return _chain(s, 100.0, self.oi, self.vol, self.spread)


class _C:
    def get_catalysts(self, s, lookback_days=14):
        return []

    def get_next_earnings(self, s):
        return None


def _providers(oi=5000, vol=2000, spread=0.05, mcap=3.0e12):
    return Providers(
        quotes=_Q(), fundamentals=_F(mcap), options=_O(oi, vol, spread),
        catalysts=_C(), gex_provider=None, catalyst_source="fake",
        gex_cross_check_source=None,
    )


def test_no_direction_exits_at_stage2():
    res = analyze("AAPL", None, _providers())
    assert res.exited_at == 2
    assert not res.passed


def test_liquid_megacap_passes_with_hard_gex():
    res = analyze("AAPL", "long", _providers())
    assert res.passed
    assert not res.share_only
    assert res.gex is not None and not res.gex.by_strike.empty
    assert res.gex.is_soft is False          # mega-cap -> hard GEX
    assert res.value_growth_score == 0.25     # 5.0 / 20.0
    assert res.structure is not None


def test_thin_name_is_share_only_and_skips_phase2():
    res = analyze("THIN", "long", _providers(oi=50, vol=20, spread=1.5))
    assert res.share_only
    statuses = {s.stage: s.status for s in res.stages}
    assert statuses[0] == "fail"
    assert statuses[3] == "skip" and statuses[4] == "skip" and statuses[5] == "skip"
    assert res.structure.instrument == "shares"


def test_small_cap_gex_is_soft():
    res = analyze("SMOL", "long", _providers(mcap=5.0e9))
    assert res.gex is not None
    assert res.gex.is_soft is True
