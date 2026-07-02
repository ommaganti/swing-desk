"""Risk-based position sizing for a small ($2,000) book.

Exact rules (config.BookRules):
  - Risk/trade = 0.75% of equity by default (0.5%-1% range) ≈ $15. This is the
    amount lost if stopped out, NOT the position size.
  - Shares:  qty       = floor(risk_$ / (entry - stop))
  - Options: contracts = floor(risk_$ / (premium_per_contract * 100))
  - Per-position cap: max loss on any single trade <= 5% of book ($100).
  - Portfolio heat cap: total open risk across all trades <= 4% of book ($80).
  - Binary-event haircut: halve the risk budget across an earnings/FDA/Fed print.

On a $2k book a single option contract often exceeds the whole risk budget. We
SURFACE that honestly ("1 contract = $X = Y% of book, exceeds budget") and
suggest alternatives rather than silently rounding to zero. Small-book lumpiness
is a feature to see, not a bug to hide.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .config import BookRules, load_book_rules
from .models import SizingResult, TradeStructure


def _clamp_risk_pct(book: BookRules, risk_pct: Optional[float]) -> float:
    rp = book.default_risk_pct if risk_pct is None else risk_pct
    return min(max(rp, book.min_risk_pct), book.max_risk_pct)


def size_trade(
    structure: TradeStructure,
    book: Optional[BookRules] = None,
    *,
    risk_pct: Optional[float] = None,
    binary_event: bool = False,
) -> SizingResult:
    """Size one trade from its structure. binary_event halves the budget."""
    book = book or load_book_rules()
    rp = _clamp_risk_pct(book, risk_pct)
    risk_dollars = book.book_size * rp
    haircut = False
    if binary_event:
        risk_dollars *= book.binary_event_haircut
        haircut = True
    cap = book.per_position_cap_dollars

    if structure.instrument == "shares":
        return _size_shares(structure, book, rp, risk_dollars, cap, haircut)
    return _size_options(structure, book, rp, risk_dollars, cap, haircut)


def _size_shares(structure, book, rp, risk_dollars, cap, haircut) -> SizingResult:
    per_share = abs(structure.entry - structure.stop)
    notes: list[str] = []
    if per_share <= 0:
        return SizingResult(
            instrument="shares", risk_dollars=risk_dollars, risk_pct=rp, quantity=0,
            position_dollars=0.0, position_pct_of_book=0.0, max_loss_dollars=0.0,
            notes=["Entry equals stop — undefined risk. Set a stop away from entry."],
            feasible=False, binary_haircut_applied=haircut,
        )
    qty = int(math.floor(risk_dollars / per_share))
    bp_capped = False
    # No-margin buying-power cap: you cannot hold more shares than cash allows.
    # At a large risk-% with a tight stop, the risk-based count can exceed the
    # whole account — cap it and surface that the actual risk drops below budget.
    if structure.entry > 0:
        max_shares_bp = int(math.floor(book.book_size / structure.entry))
        if qty > max_shares_bp:
            qty = max_shares_bp
            bp_capped = True
    max_loss = qty * per_share
    pos = qty * structure.entry
    cap_pct = book.per_position_cap_pct * 100
    exceeds_cap = max_loss > cap
    if qty == 0:
        notes.append(
            f"Risk budget ${risk_dollars:.0f} ÷ ${per_share:.2f}/share < 1 share. "
            "Stop is too far for this book — tighten the stop or skip the trade."
        )
    if bp_capped:
        notes.append(
            f"Position capped by buying power (no margin): {qty} shares = "
            f"${pos:,.0f} (~100% of book). Actual risk is now ${max_loss:.0f}, "
            f"below the ${risk_dollars:.0f} budget — the stop is too tight to deploy full risk."
        )
    if exceeds_cap:
        notes.append(
            f"Max loss ${max_loss:.0f} exceeds the {cap_pct:.0f}% per-position cap "
            f"(${cap:.0f}). Reduce size or widen the stop distance / lower entry."
        )
    if haircut:
        notes.append("Binary-event haircut applied: risk budget halved for a print held through.")
    return SizingResult(
        instrument="shares", risk_dollars=risk_dollars, risk_pct=rp, quantity=qty,
        position_dollars=pos, position_pct_of_book=pos / book.book_size,
        max_loss_dollars=max_loss, notes=notes, exceeds_position_cap=exceeds_cap,
        binary_haircut_applied=haircut, feasible=qty > 0,
    )


def _size_options(structure, book, rp, risk_dollars, cap, haircut) -> SizingResult:
    prem = structure.premium_per_contract
    notes: list[str] = []
    if not prem or prem <= 0:
        return SizingResult(
            instrument=structure.instrument, risk_dollars=risk_dollars, risk_pct=rp,
            quantity=0, position_dollars=0.0, position_pct_of_book=0.0, max_loss_dollars=0.0,
            notes=["No option premium available to size against — use shares or supply a premium."],
            feasible=False, binary_haircut_applied=haircut,
        )
    cost_per = prem * 100.0  # defined-risk long option: max loss per contract
    one_pct = cost_per / book.book_size
    contracts_by_budget = int(math.floor(risk_dollars / cost_per))

    # Surface the small-book lumpiness honestly when one contract blows the budget.
    if contracts_by_budget == 0:
        notes.append(
            f"1 contract = ${cost_per:.0f} = {one_pct*100:.1f}% of book, exceeds the "
            f"${risk_dollars:.0f} risk budget. Options: trade shares instead, use a "
            "cheaper debit spread, or explicitly accept the oversize before proceeding."
        )
        return SizingResult(
            instrument=structure.instrument, risk_dollars=risk_dollars, risk_pct=rp,
            quantity=0, position_dollars=0.0, position_pct_of_book=one_pct,
            max_loss_dollars=cost_per, notes=notes, exceeds_risk_budget=True,
            exceeds_position_cap=cost_per > cap, binary_haircut_applied=haircut, feasible=False,
        )

    # Respect the per-position cap (a long option's max loss is its premium) and
    # the no-margin buying-power limit (premium outlay cannot exceed cash).
    contracts_by_cap = int(math.floor(cap / cost_per))
    contracts_by_bp = int(math.floor(book.book_size / cost_per))
    contracts = min(contracts_by_budget, contracts_by_cap, contracts_by_bp)
    exceeds_cap = contracts_by_cap < contracts_by_budget
    if exceeds_cap:
        notes.append(
            f"Per-position cap (${cap:.0f}) binds before the risk budget — "
            f"capped at {contracts} contract(s)."
        )
    if contracts_by_bp < min(contracts_by_budget, contracts_by_cap):
        notes.append(
            f"Buying power (no margin) caps premium outlay at {contracts} contract(s) = ${contracts*cost_per:,.0f}."
        )
    max_loss = contracts * cost_per
    if haircut:
        notes.append("Binary-event haircut applied: risk budget halved for a print held through.")

    return SizingResult(
        instrument=structure.instrument, risk_dollars=risk_dollars, risk_pct=rp,
        quantity=contracts, position_dollars=max_loss, position_pct_of_book=max_loss / book.book_size,
        max_loss_dollars=max_loss, notes=notes, exceeds_position_cap=exceeds_cap,
        binary_haircut_applied=haircut, feasible=contracts > 0,
    )


@dataclass
class HeatStatus:
    open_risk_dollars: float
    new_risk_dollars: float
    total_risk_dollars: float
    cap_dollars: float
    within_cap: bool
    message: str


def portfolio_heat_status(
    open_risk_dollars: float,
    new_risk_dollars: float,
    book: Optional[BookRules] = None,
) -> HeatStatus:
    """Check total open risk (existing + this trade) against the portfolio heat cap."""
    book = book or load_book_rules()
    total = open_risk_dollars + new_risk_dollars
    cap = book.portfolio_heat_cap_dollars
    cap_pct = book.portfolio_heat_cap_pct * 100
    within = total <= cap
    pct = total / book.book_size * 100
    if within:
        msg = (f"Open risk ${total:.0f} / ${cap:.0f} cap ({pct:.1f}% of book). "
               f"Within the {cap_pct:.0f}% portfolio heat cap.")
    else:
        msg = (f"Open risk ${total:.0f} EXCEEDS the ${cap:.0f} heat cap "
               f"({pct:.1f}% of book). Close or shrink a position before adding this one.")
    return HeatStatus(open_risk_dollars, new_risk_dollars, total, cap, within, msg)
