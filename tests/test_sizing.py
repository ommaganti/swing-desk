from swingdesk.config import BookRules
from swingdesk.models import TradeStructure
from swingdesk.sizing import portfolio_heat_status, size_trade

BOOK = BookRules()  # $2,000, 10% default risk ($200), caps 10%/40%


def _shares(entry, stop):
    return TradeStructure("shares", "long", entry=entry, stop=stop, target=entry * 1.1, rationale="")


def _opt(premium):
    return TradeStructure("long_call", "long", entry=100, stop=98, target=110,
                          rationale="", strike=100, premium_per_contract=premium)


def test_shares_risk_bound_when_stop_is_wide():
    # entry 100 / stop 80 -> $20/share. Risk $200 -> 10 shares. BP allows 20, no bind.
    sr = size_trade(_shares(100.0, 80.0), BOOK)
    assert sr.quantity == 10
    assert sr.max_loss_dollars == 200.0
    assert abs(sr.position_dollars - 1000.0) < 1e-6
    assert sr.feasible


def test_shares_capped_by_buying_power_when_stop_is_tight():
    # entry 100 / stop 98 -> $2/share. Risk $200 -> 100 shares, but only $2,000
    # cash buys 20 shares. Must cap to 20; actual risk drops to $40.
    sr = size_trade(_shares(100.0, 98.0), BOOK)
    assert sr.quantity == 20
    assert abs(sr.position_dollars - 2000.0) < 1e-6
    assert sr.max_loss_dollars == 40.0
    assert any("buying power" in n.lower() for n in sr.notes)
    assert sr.feasible


def test_shares_entry_equals_stop_is_infeasible():
    sr = size_trade(_shares(100.0, 100.0), BOOK)
    assert not sr.feasible
    assert sr.quantity == 0


def test_expensive_single_option_exceeds_budget_is_surfaced():
    sr = size_trade(_opt(3.00), BOOK)  # 1 contract = $300 > $200 budget
    assert sr.quantity == 0
    assert sr.exceeds_risk_budget
    assert not sr.feasible
    assert sr.max_loss_dollars == 300.0
    assert any("exceeds" in n.lower() for n in sr.notes)


def test_affordable_option_fits_at_new_risk():
    sr = size_trade(_opt(1.50), BOOK)  # 1 contract = $150 < $200 budget
    assert sr.quantity == 1
    assert sr.max_loss_dollars == 150.0
    assert sr.feasible


def test_binary_haircut_halves_risk():
    base = size_trade(_shares(100.0, 80.0), BOOK)          # risk $200 -> 10 shares
    cut = size_trade(_shares(100.0, 80.0), BOOK, binary_event=True)  # risk $100 -> 5
    assert cut.binary_haircut_applied
    assert cut.risk_dollars == base.risk_dollars / 2
    assert cut.quantity == 5


def test_risk_pct_is_clamped_to_band():
    hi = size_trade(_shares(100.0, 80.0), BOOK, risk_pct=0.50)  # 50% -> clamp to 20%
    assert abs(hi.risk_pct - BOOK.max_risk_pct) < 1e-9


def test_portfolio_heat_cap_at_40_percent():
    within = portfolio_heat_status(400.0, 200.0, BOOK)   # 600 <= 800
    over = portfolio_heat_status(700.0, 200.0, BOOK)      # 900 > 800
    assert within.within_cap
    assert not over.within_cap
    assert over.cap_dollars == 800.0
