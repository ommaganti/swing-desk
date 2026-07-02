"""Typed data models shared across the data layer, analysis engine, and UI.

Every model that originates from a data provider carries `source` and
`is_delayed` so the dashboard can honestly flag where a number came from and
whether it is delayed (house convention, see qqq_to_nq_gex.py's Quote).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional

import pandas as pd

Right = Literal["C", "P"]
Direction = Literal["long", "short"]
Regime = Literal["positive", "negative"]


# --------------------------------------------------------------------------- #
# Market data                                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class Quote:
    symbol: str
    price: float
    as_of: datetime
    source: str
    is_delayed: bool = False
    typical_delay_min: int = 0


@dataclass
class Fundamentals:
    symbol: str
    source: str
    ps_ttm: Optional[float] = None            # price / sales (trailing twelve months)
    revenue_growth_pct: Optional[float] = None  # YoY revenue growth, in PERCENT (e.g. 25.0)
    market_cap: Optional[float] = None
    sector: Optional[str] = None
    analyst_high: Optional[float] = None
    analyst_low: Optional[float] = None
    analyst_mean: Optional[float] = None


@dataclass
class ExpiryChain:
    """One expiry's calls/puts. DataFrames follow the yfinance column shape plus
    a computed `gamma` column: strike, bid, ask, lastPrice, volume, openInterest,
    impliedVolatility, gamma.
    """
    expiry: date
    dte: int
    calls: pd.DataFrame
    puts: pd.DataFrame


@dataclass
class OptionChain:
    symbol: str
    spot: float
    as_of: datetime
    source: str
    is_delayed: bool
    by_expiry: dict[date, ExpiryChain] = field(default_factory=dict)

    @property
    def expiries(self) -> list[date]:
        return sorted(self.by_expiry)

    def nearest(self, min_dte: int = 0) -> Optional[ExpiryChain]:
        """First expiry with dte >= min_dte (defaults to the nearest expiry)."""
        for exp in self.expiries:
            ec = self.by_expiry[exp]
            if ec.dte >= min_dte:
                return ec
        return None


# --------------------------------------------------------------------------- #
# Positioning (Phase 2)                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class GexProfile:
    symbol: str
    spot: float
    net_gex: float
    regime: Regime                 # "positive" => range/mean-revert; "negative" => trend/amplify
    gamma_flip: Optional[float]    # spot level where cumulative GEX crosses zero
    call_wall: Optional[float]     # strike with largest positive gamma above spot
    put_wall: Optional[float]      # strike with largest |gamma| below spot
    by_strike: pd.DataFrame        # columns: strike, call_gex, put_gex, net_gex, cum_gex
    source: str
    is_delayed: bool = True
    is_soft: bool = False          # True when single-name GEX is not a liquid mega-cap
    note: str = ""


@dataclass
class IVReadout:
    front_atm_iv: Optional[float] = None
    back_atm_iv: Optional[float] = None
    iv_term_structure: Optional[float] = None    # front - back; >0 => crush risk
    risk_reversal_25d: Optional[float] = None     # 25d put IV - 25d call IV; >0 => downside demand
    expected_move_dollars: Optional[float] = None  # straddle-implied move to horizon
    expected_move_pct: Optional[float] = None
    front_expiry: Optional[date] = None
    back_expiry: Optional[date] = None


# --------------------------------------------------------------------------- #
# Catalysts (Phase 1)                                                            #
# --------------------------------------------------------------------------- #
CatalystKind = Literal[
    "earnings", "fda", "fed", "news", "partnership", "regulatory", "other"
]


@dataclass
class Catalyst:
    kind: CatalystKind
    headline: str
    source: str
    when: Optional[date] = None
    dated: bool = False     # has a known date on the calendar
    binary: bool = False    # outcome is a discrete print (earnings/FDA/Fed)
    url: Optional[str] = None


# --------------------------------------------------------------------------- #
# Funnel result                                                                  #
# --------------------------------------------------------------------------- #
StageStatus = Literal["pass", "fail", "warn", "skip"]


@dataclass
class StageResult:
    stage: int
    name: str
    status: StageStatus
    summary: str
    detail: dict = field(default_factory=dict)


@dataclass
class FunnelResult:
    symbol: str
    direction: Optional[Direction]
    stages: list[StageResult] = field(default_factory=list)
    share_only: bool = False        # failed Stage 0 — no options/GEX layer
    exited_at: Optional[int] = None  # stage index where the funnel short-circuited
    # Carried artefacts (populated as stages run).
    quote: Optional[Quote] = None
    fundamentals: Optional[Fundamentals] = None
    oi_as_of: Optional[str] = None   # "live", a cache capture time, or None
    catalysts: list[Catalyst] = field(default_factory=list)
    next_earnings: Optional[date] = None
    value_growth_score: Optional[float] = None
    gex: Optional[GexProfile] = None
    index_gex: Optional[GexProfile] = None
    iv: Optional[IVReadout] = None
    structure: Optional["TradeStructure"] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if the funnel reached Stage 6 without exiting on a hard gate."""
        return self.exited_at is None

    def add(self, sr: StageResult) -> None:
        self.stages.append(sr)


# --------------------------------------------------------------------------- #
# Structure + sizing (Phase 2 handoff -> sizing engine)                          #
# --------------------------------------------------------------------------- #
Instrument = Literal["shares", "long_call", "long_put", "debit_spread"]


@dataclass
class TradeStructure:
    instrument: Instrument
    direction: Direction
    entry: float
    stop: float
    target: float
    rationale: str
    # Optional option leg details when instrument is an option.
    strike: Optional[float] = None
    expiry: Optional[date] = None
    premium_per_contract: Optional[float] = None  # per-share premium (multiply by 100 for $)


@dataclass
class SizingResult:
    instrument: Instrument
    risk_dollars: float
    risk_pct: float
    quantity: int                 # shares, or contracts
    position_dollars: float
    position_pct_of_book: float
    max_loss_dollars: float
    notes: list[str] = field(default_factory=list)
    exceeds_risk_budget: bool = False
    exceeds_position_cap: bool = False
    binary_haircut_applied: bool = False
    feasible: bool = True


@dataclass
class PreMortem:
    bear_case: str
    invalidation_evidence: str
    historical_base_rate: str

    @property
    def complete(self) -> bool:
        return all(
            bool(s and s.strip())
            for s in (self.bear_case, self.invalidation_evidence, self.historical_base_rate)
        )
