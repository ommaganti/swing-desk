"""OPEX + macro (FOMC/CPI) calendar.

Monthly/quarterly OPEX are computed locally (no API): monthly OPEX is the 3rd
Friday; quarterly OPEX is the 3rd Friday of Mar/Jun/Sep/Dec. The 3rd-Friday math
is the same logic proven in the workspace's qqq_to_nq_gex.py.

FOMC/CPI dates come from a maintained local JSON list (data/fomc_cpi_dates.json)
so the tool needs no economic-calendar API; swap in an API later behind
`load_macro_dates()` without touching callers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .config import MACRO_DATES_FILE

_QUARTERLY_MONTHS = (3, 6, 9, 12)


def third_friday(year: int, month: int) -> date:
    """3rd Friday of (year, month). Mon=0..Fri=4."""
    first = date(year, month, 1)
    days_to_first_friday = (4 - first.weekday()) % 7
    return first + timedelta(days=days_to_first_friday + 14)


def is_quarterly_opex(d: date) -> bool:
    return d.month in _QUARTERLY_MONTHS and d == third_friday(d.year, d.month)


def next_monthly_opex(from_date: Optional[date] = None) -> date:
    """The next monthly OPEX (3rd Friday) on or after `from_date`."""
    d = from_date or date.today()
    tf = third_friday(d.year, d.month)
    if tf >= d:
        return tf
    nxt_month = d.month % 12 + 1
    nxt_year = d.year + (1 if d.month == 12 else 0)
    return third_friday(nxt_year, nxt_month)


def opex_in_window(start: date, end: date) -> list[date]:
    """All monthly OPEX dates within [start, end] inclusive."""
    out: list[date] = []
    d = next_monthly_opex(start)
    while d <= end:
        out.append(d)
        nm = d.month % 12 + 1
        ny = d.year + (1 if d.month == 12 else 0)
        d = third_friday(ny, nm)
    return out


# --------------------------------------------------------------------------- #
# Macro events (FOMC / CPI) from the maintained local list.                     #
# --------------------------------------------------------------------------- #
@dataclass
class MacroEvent:
    when: date
    label: str       # e.g. "FOMC decision", "CPI release"
    kind: str        # "fomc" | "cpi" | other


def load_macro_dates(path=MACRO_DATES_FILE) -> list[MacroEvent]:
    """Load FOMC/CPI dates from JSON. Returns [] (not an error) if the file is
    missing, so the macro flag degrades gracefully rather than crashing."""
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    events: list[MacroEvent] = []
    for item in raw.get("events", []):
        try:
            events.append(
                MacroEvent(
                    when=date.fromisoformat(item["date"]),
                    label=item.get("label", item.get("kind", "macro")),
                    kind=item.get("kind", "other"),
                )
            )
        except (KeyError, ValueError):
            continue  # skip malformed rows rather than fail the whole load
    return sorted(events, key=lambda e: e.when)


def macro_events_in_window(start: date, end: date, path=MACRO_DATES_FILE) -> list[MacroEvent]:
    return [e for e in load_macro_dates(path) if start <= e.when <= end]


@dataclass
class CalendarFlags:
    """What date-based risks a hold window from `start` to `end` crosses."""
    opex_dates: list[date]
    quarterly_opex: bool
    macro_events: list[MacroEvent]

    @property
    def crosses_opex(self) -> bool:
        return bool(self.opex_dates)

    @property
    def crosses_macro(self) -> bool:
        return bool(self.macro_events)

    @property
    def any_flag(self) -> bool:
        return self.crosses_opex or self.crosses_macro


def flags_for_window(start: date, end: date) -> CalendarFlags:
    """OPEX + macro events the hold window crosses. Drives the discipline flag
    that requires a regime re-read on the far side of OPEX (gamma rolls off at
    expiration and the regime can flip)."""
    opex = opex_in_window(start, end)
    return CalendarFlags(
        opex_dates=opex,
        quarterly_opex=any(is_quarterly_opex(d) for d in opex),
        macro_events=macro_events_in_window(start, end),
    )
