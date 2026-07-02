"""Decision-discipline gates — built into the tool, not optional.

  - Pre-mortem REQUIRED before any sizing output (bear case + invalidation
    evidence + historical base rate). No sizing card renders until these exist.
  - Expected-move flag: target inside the implied move => "no edge" banner.
  - Correlation warning: a new ticker sharing sector/beta with an open position
    may be one bet sized up, not a new trade.
  - OPEX / macro flag: if the hold window crosses an OPEX/FOMC/CPI date, flag it
    and require a regime re-read on the far side of OPEX (gamma rolls off at
    expiration and the regime can flip).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .calendar_util import flags_for_window
from .models import FunnelResult, PreMortem

Level = str  # "block" | "warn" | "info" | "ok"


@dataclass
class DisciplineCheck:
    name: str
    level: Level
    message: str
    detail: dict = field(default_factory=dict)

    @property
    def blocks_sizing(self) -> bool:
        return self.level == "block"


def premortem_gate(pm: Optional[PreMortem]) -> DisciplineCheck:
    """The hard gate: sizing must not render until a complete pre-mortem exists."""
    if pm is None or not pm.complete:
        missing = []
        if pm is None or not (pm.bear_case or "").strip():
            missing.append("bear case")
        if pm is None or not (pm.invalidation_evidence or "").strip():
            missing.append("invalidation evidence")
        if pm is None or not (pm.historical_base_rate or "").strip():
            missing.append("historical base rate")
        return DisciplineCheck(
            "Pre-mortem", "block",
            "Complete the pre-mortem before sizing — missing: " + ", ".join(missing) + ".",
            {"missing": missing},
        )
    return DisciplineCheck("Pre-mortem", "ok", "Pre-mortem complete — sizing unlocked.")


def expected_move_check(funnel: FunnelResult) -> DisciplineCheck:
    iv = funnel.iv
    if iv is None or iv.expected_move_dollars is None:
        return DisciplineCheck("Expected move", "info", "Expected move unavailable.")
    no_edge = any(s.detail.get("no_edge") for s in funnel.stages if s.stage == 5)
    if no_edge:
        return DisciplineCheck(
            "Expected move", "warn",
            f"No edge — target sits inside the implied move (±${iv.expected_move_dollars:.2f}). "
            "The market already prices this.",
            {"expected_move": iv.expected_move_dollars},
        )
    return DisciplineCheck(
        "Expected move", "ok",
        f"Target is beyond the implied move (±${iv.expected_move_dollars:.2f}).",
        {"expected_move": iv.expected_move_dollars},
    )


def correlation_check(
    sector: Optional[str],
    open_position_sectors: dict[str, str],
    symbol: str,
) -> DisciplineCheck:
    """Warn if `symbol`'s sector matches an open position's sector."""
    if not sector:
        return DisciplineCheck("Correlation", "info", "Sector unknown — cannot check correlation.")
    clashes = [t for t, sec in open_position_sectors.items()
               if sec and sec == sector and t.upper() != symbol.upper()]
    if clashes:
        return DisciplineCheck(
            "Correlation", "warn",
            f"{symbol} is {sector}, same sector as open position(s): {', '.join(clashes)}. "
            "This may be ONE bet sized up, not a new uncorrelated trade.",
            {"sector": sector, "clashes": clashes},
        )
    return DisciplineCheck("Correlation", "ok", f"No open position shares {symbol}'s sector ({sector}).")


def calendar_check(hold_days: int, start: Optional[date] = None) -> DisciplineCheck:
    """Flag OPEX/FOMC/CPI inside the hold window; require a regime re-read past OPEX."""
    start = start or date.today()
    end = start + timedelta(days=hold_days)
    f = flags_for_window(start, end)
    if not f.any_flag:
        return DisciplineCheck("OPEX / macro", "ok",
                              f"No OPEX/FOMC/CPI dates in the next {hold_days}d.")
    bits = []
    if f.crosses_opex:
        opex = ", ".join(d.isoformat() for d in f.opex_dates)
        q = " (QUARTERLY)" if f.quarterly_opex else ""
        bits.append(f"OPEX {opex}{q} — re-read the GEX regime AFTER OPEX; gamma rolls off and the regime can flip")
    if f.crosses_macro:
        ev = ", ".join(f"{e.label} {e.when.isoformat()}" for e in f.macro_events)
        bits.append(f"macro: {ev}")
    return DisciplineCheck(
        "OPEX / macro", "warn", "Hold window crosses: " + "; ".join(bits) + ".",
        {"opex": [d.isoformat() for d in f.opex_dates],
         "quarterly": f.quarterly_opex,
         "macro": [(e.kind, e.when.isoformat()) for e in f.macro_events]},
    )


def run_all(
    funnel: FunnelResult,
    pm: Optional[PreMortem],
    hold_days: int,
    open_position_sectors: Optional[dict[str, str]] = None,
) -> list[DisciplineCheck]:
    """Convenience: every discipline check in display order."""
    sector = funnel.fundamentals.sector if funnel.fundamentals else None
    return [
        premortem_gate(pm),
        expected_move_check(funnel),
        correlation_check(sector, open_position_sectors or {}, funnel.symbol),
        calendar_check(hold_days),
    ]
