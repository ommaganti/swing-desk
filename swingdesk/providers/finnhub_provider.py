"""Finnhub catalyst provider — company news + earnings calendar (free tier).

Free tier: 60 calls/min (~300/day), no cost. Needs FINNHUB_API_KEY in .env.
Used for Stage 1 (catalyst). Classifies each item dated/binary so the funnel can
treat an upcoming earnings/FDA/Fed print differently from undated drift.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import get_key
from ..models import Catalyst, CatalystKind
from .base import CatalystProvider

_BASE = "https://finnhub.io/api/v1"

# Keyword -> catalyst kind. Binary kinds (earnings/fda/fed) are discrete prints.
_KIND_KEYWORDS: list[tuple[CatalystKind, tuple[str, ...]]] = [
    ("fda", ("fda", "phase 3", "phase iii", "clinical", "approval", "trial")),
    ("fed", ("fomc", "federal reserve", "rate decision", "powell")),
    ("partnership", ("partnership", "partners with", "collaboration", "deal with")),
    ("regulatory", ("sec ", "doj", "antitrust", "lawsuit", "investigation", "subpoena")),
    ("earnings", ("earnings", "q1 ", "q2 ", "q3 ", "q4 ", "guidance", "revenue beat")),
]
_BINARY_KINDS = {"earnings", "fda", "fed"}


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _classify(headline: str) -> CatalystKind:
    h = headline.lower()
    for kind, kws in _KIND_KEYWORDS:
        if any(kw in h for kw in kws):
            return kind
    return "news"


class FinnhubProvider(CatalystProvider):
    source = "Finnhub"

    def __init__(self) -> None:
        self._key = get_key("finnhub")
        if not self._key:
            raise RuntimeError("FinnhubProvider requires FINNHUB_API_KEY")
        self._s = _session()

    def _get(self, path: str, params: dict) -> Optional[object]:
        params = {**params, "token": self._key}
        try:
            r = self._s.get(f"{_BASE}/{path}", params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None  # fail soft: caller degrades, never crashes the funnel

    def get_catalysts(self, symbol: str, lookback_days: int = 14) -> list[Catalyst]:
        to = date.today()
        frm = to - timedelta(days=lookback_days)
        data = self._get("company-news", {
            "symbol": symbol, "from": frm.isoformat(), "to": to.isoformat(),
        })
        out: list[Catalyst] = []
        if isinstance(data, list):
            for item in data[:40]:
                headline = str(item.get("headline", "")).strip()
                if not headline:
                    continue
                kind = _classify(headline)
                when = None
                ts = item.get("datetime")
                if isinstance(ts, (int, float)) and ts > 0:
                    when = datetime.utcfromtimestamp(ts).date()
                out.append(Catalyst(
                    kind=kind, headline=headline, source=self.source, when=when,
                    dated=False, binary=False, url=item.get("url"),
                ))
        return out

    def get_next_earnings(self, symbol: str) -> Optional[date]:
        to = date.today() + timedelta(days=120)
        frm = date.today()
        data = self._get("calendar/earnings", {
            "symbol": symbol, "from": frm.isoformat(), "to": to.isoformat(),
        })
        if isinstance(data, dict):
            rows = data.get("earningsCalendar") or []
            dates = []
            for row in rows:
                try:
                    d = date.fromisoformat(row["date"])
                    if d >= frm:
                        dates.append(d)
                except (KeyError, ValueError):
                    continue
            if dates:
                return min(dates)
        return None
