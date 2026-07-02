"""Abstract provider interfaces.

Analysis code depends only on these ABCs, never on a concrete provider, so a
provider can be swapped (yfinance -> Tradier/Polygon, local GEX -> FlashAlpha)
without touching the funnel. Every method returns a typed model from models.py
carrying `source`/`is_delayed` where applicable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from ..models import Catalyst, Fundamentals, GexProfile, OptionChain, Quote


class QuoteProvider(ABC):
    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...


class FundamentalsProvider(ABC):
    @abstractmethod
    def get_fundamentals(self, symbol: str) -> Fundamentals: ...


class OptionsProvider(ABC):
    @abstractmethod
    def get_chain(self, symbol: str, max_expiries: int = 4) -> OptionChain: ...


class CatalystProvider(ABC):
    @abstractmethod
    def get_catalysts(self, symbol: str, lookback_days: int = 14) -> list[Catalyst]: ...

    @abstractmethod
    def get_next_earnings(self, symbol: str) -> Optional[date]: ...


class GexProvider(ABC):
    """Optional hosted GEX source (e.g. FlashAlpha) used to CROSS-CHECK the
    locally-computed profile. Returns None on any failure so local GEX stands."""

    @abstractmethod
    def get_gex(self, symbol: str, spot: Optional[float] = None) -> Optional[GexProfile]: ...
