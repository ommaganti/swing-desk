from datetime import date

from swingdesk.calendar_util import (
    is_quarterly_opex,
    macro_events_in_window,
    next_monthly_opex,
    opex_in_window,
    third_friday,
)


def test_third_friday_known_values():
    assert third_friday(2026, 1) == date(2026, 1, 16)
    assert third_friday(2026, 6) == date(2026, 6, 19)
    assert third_friday(2026, 7) == date(2026, 7, 17)


def test_quarterly_opex_flag():
    assert is_quarterly_opex(date(2026, 6, 19))      # June = quarterly
    assert not is_quarterly_opex(date(2026, 1, 16))  # Jan = monthly only
    assert not is_quarterly_opex(date(2026, 6, 18))  # not the 3rd Friday


def test_next_monthly_opex_rolls_forward():
    assert next_monthly_opex(date(2026, 6, 20)) == date(2026, 7, 17)
    assert next_monthly_opex(date(2026, 6, 1)) == date(2026, 6, 19)


def test_opex_in_window():
    got = opex_in_window(date(2026, 6, 1), date(2026, 8, 1))
    assert got == [date(2026, 6, 19), date(2026, 7, 17)]


def test_macro_events_loaded_from_local_list():
    ev = macro_events_in_window(date(2026, 7, 1), date(2026, 8, 1))
    kinds = {(e.kind, e.when.isoformat()) for e in ev}
    assert ("fomc", "2026-07-29") in kinds
    assert ("cpi", "2026-07-15") in kinds
