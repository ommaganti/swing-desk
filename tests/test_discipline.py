from swingdesk.discipline import (
    calendar_check,
    correlation_check,
    expected_move_check,
    premortem_gate,
)
from swingdesk.models import FunnelResult, IVReadout, PreMortem, StageResult


def test_premortem_gate_blocks_until_complete():
    assert premortem_gate(None).blocks_sizing
    assert premortem_gate(PreMortem("bear", "", "rate")).blocks_sizing
    ok = premortem_gate(PreMortem("bear case", "invalidation", "base rate"))
    assert not ok.blocks_sizing
    assert ok.level == "ok"


def test_expected_move_no_edge_warns():
    res = FunnelResult(symbol="X", direction="long")
    res.iv = IVReadout(expected_move_dollars=5.0)
    res.add(StageResult(5, "Implied vol", "warn", "", {"no_edge": True}))
    chk = expected_move_check(res)
    assert chk.level == "warn"


def test_expected_move_with_edge_is_ok():
    res = FunnelResult(symbol="X", direction="long")
    res.iv = IVReadout(expected_move_dollars=5.0)
    res.add(StageResult(5, "Implied vol", "pass", "", {"no_edge": False}))
    assert expected_move_check(res).level == "ok"


def test_correlation_warns_on_same_sector():
    chk = correlation_check("Technology", {"MSFT": "Technology"}, "AAPL")
    assert chk.level == "warn"
    assert "MSFT" in chk.message


def test_correlation_ok_when_no_overlap():
    chk = correlation_check("Energy", {"MSFT": "Technology"}, "XOM")
    assert chk.level == "ok"


def test_calendar_check_flags_long_window():
    # A 45-day window always contains a monthly OPEX (3rd Friday).
    chk = calendar_check(45)
    assert chk.level in ("warn",)
