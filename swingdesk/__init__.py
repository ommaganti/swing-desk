"""swingdesk — a local, read-only swing-trade decision-support desk.

NOT a trading system. NOT financial advice. It surfaces structured data,
risk-based sizing math, and decision-discipline gates. The user acts on the
output themselves; the tool never places orders or connects to a broker for
execution.

Two jobs are kept strictly separate (see analysis.py):
  Phase 1 (selection): WHAT to trade / which direction — catalyst + valuation.
  Phase 2 (timing):    WHEN to enter / how to structure — GEX, OI, volume, IV.
Positioning data never generates a thesis; it only refines a thesis that has
already passed Phase 1.
"""
from __future__ import annotations

__version__ = "0.1.0"
