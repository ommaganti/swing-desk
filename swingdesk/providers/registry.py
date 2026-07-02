"""Provider selection. Reads the environment and wires concrete providers,
always guaranteeing a working zero-key path (yfinance + local GEX + fallback
catalysts). The hosted GEX provider is optional and only ever a cross-check.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import has_key
from .base import (
    CatalystProvider,
    FundamentalsProvider,
    GexProvider,
    OptionsProvider,
    QuoteProvider,
)
from .yfinance_provider import YFinanceProvider


@dataclass
class Providers:
    quotes: QuoteProvider
    fundamentals: FundamentalsProvider
    options: OptionsProvider
    catalysts: CatalystProvider
    gex_provider: Optional[GexProvider]  # hosted cross-check (FlashAlpha) or None
    catalyst_source: str
    gex_cross_check_source: Optional[str]
    options_source: str = "yfinance"


def build_providers() -> Providers:
    yf = YFinanceProvider()

    # Option chains: Tradier (real OI + native greeks) if keyed, else yfinance
    # (delayed; open interest is often zeroed outside market hours).
    if has_key("tradier"):
        from .tradier_provider import TradierOptionsProvider
        options: OptionsProvider = TradierOptionsProvider()
        options_source = "Tradier (real OI + greeks)"
    else:
        options = yf
        options_source = "yfinance (delayed; OI may be 0 off-hours)"

    # Catalysts: Finnhub if keyed, else the zero-key yfinance-news fallback.
    if has_key("finnhub"):
        from .finnhub_provider import FinnhubProvider
        catalysts: CatalystProvider = FinnhubProvider()
        catalyst_source = "Finnhub"
    else:
        from .websearch_catalyst import FallbackCatalystProvider
        catalysts = FallbackCatalystProvider(yf)
        catalyst_source = "yfinance news (no key)"

    # Hosted GEX cross-check: FlashAlpha if keyed, else None (local GEX stands).
    gex_provider: Optional[GexProvider] = None
    gex_cross_check_source: Optional[str] = None
    if has_key("flashalpha"):
        from .flashalpha_provider import FlashAlphaProvider
        gex_provider = FlashAlphaProvider()
        gex_cross_check_source = "FlashAlpha"

    return Providers(
        quotes=yf,
        fundamentals=yf,
        options=options,
        catalysts=catalysts,
        gex_provider=gex_provider,
        catalyst_source=catalyst_source,
        gex_cross_check_source=gex_cross_check_source,
        options_source=options_source,
    )
