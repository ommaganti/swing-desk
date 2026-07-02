"""Zero-key catalyst fallback (used when no FINNHUB_API_KEY is set).

Sources recent headlines from yfinance's `.news` (free, no key) and earnings
dates from the yfinance provider. This is the slot for a richer web-search /
LLM-summarization step later — keep the CatalystProvider return types and drop
in a new body without touching the funnel.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import yfinance as yf

from ..models import Catalyst
from .base import CatalystProvider
from .finnhub_provider import _classify  # reuse the headline classifier
from .yfinance_provider import YFinanceProvider


class FallbackCatalystProvider(CatalystProvider):
    source = "yfinance news (no key)"

    def __init__(self, yf_provider: Optional[YFinanceProvider] = None) -> None:
        self._yf = yf_provider or YFinanceProvider()

    def get_catalysts(self, symbol: str, lookback_days: int = 14) -> list[Catalyst]:
        try:
            news = yf.Ticker(symbol).news or []
        except Exception:
            news = []
        out: list[Catalyst] = []
        for item in news[:40]:
            # yfinance has shipped two shapes: flat, and nested under "content".
            content = item.get("content", item)
            headline = str(content.get("title") or item.get("title") or "").strip()
            if not headline:
                continue
            when = self._parse_when(item, content)
            url = None
            cu = content.get("canonicalUrl") or content.get("clickThroughUrl")
            if isinstance(cu, dict):
                url = cu.get("url")
            url = url or item.get("link")
            out.append(Catalyst(
                kind=_classify(headline), headline=headline, source=self.source,
                when=when, dated=False, binary=False, url=url,
            ))
        return out

    @staticmethod
    def _parse_when(item: dict, content: dict) -> Optional[date]:
        ts = item.get("providerPublishTime")
        if isinstance(ts, (int, float)) and ts > 0:
            return datetime.utcfromtimestamp(ts).date()
        pd = content.get("pubDate") or content.get("displayTime")
        if isinstance(pd, str):
            try:
                return datetime.fromisoformat(pd.replace("Z", "+00:00")).date()
            except ValueError:
                return None
        return None

    def get_next_earnings(self, symbol: str) -> Optional[date]:
        return self._yf.get_next_earnings(symbol)
