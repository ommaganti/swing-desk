"""yfinance baseline provider — quotes, fundamentals, option chains, earnings.

Zero key, free. Quotes are effectively near-real-time during RTH; option chains
are delayed (~15 min) and yfinance does NOT return greeks, so the GEX layer
computes gamma from the chain's `impliedVolatility` column (see greeks/gex).
This is the swap point — replace with Tradier/Polygon by keeping the return
types identical.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf

from ..models import ExpiryChain, Fundamentals, OptionChain, Quote
from .base import FundamentalsProvider, OptionsProvider, QuoteProvider

_UTC = timezone.utc
# Yahoo option chains are delayed; surface that honestly on every chain.
_CHAIN_DELAY_MIN = 15


class YFinanceProvider(QuoteProvider, FundamentalsProvider, OptionsProvider):
    source = "Yahoo Finance (yfinance)"

    # ----------------------------- quotes ----------------------------------- #
    def get_quote(self, symbol: str) -> Quote:
        t = yf.Ticker(symbol)
        price, ts = self._last_price(t, symbol)
        return Quote(
            symbol=symbol, price=price, as_of=ts, source=self.source,
            is_delayed=False, typical_delay_min=0,
        )

    @staticmethod
    def _last_price(t: "yf.Ticker", symbol: str) -> tuple[float, datetime]:
        """fast_info first (one round-trip); fall back to intraday history.
        Fail loud on a non-positive price — a bad spot poisons GEX and sizing."""
        try:
            last = float(t.fast_info["last_price"])
            if last > 0:
                return last, datetime.now(tz=_UTC)
        except Exception:
            pass
        hist = t.history(period="1d", interval="1m", auto_adjust=False)
        if hist.empty:
            hist = t.history(period="5d", interval="5m", auto_adjust=False)
        if hist.empty:
            raise RuntimeError(f"No price data returned for {symbol}")
        price = float(hist["Close"].iloc[-1])
        ts = hist.index[-1].to_pydatetime()
        ts = ts.replace(tzinfo=_UTC) if ts.tzinfo is None else ts.astimezone(_UTC)
        if price <= 0:
            raise RuntimeError(f"Non-positive price for {symbol}: {price}")
        return price, ts

    # --------------------------- fundamentals ------------------------------- #
    def get_fundamentals(self, symbol: str) -> Fundamentals:
        info = {}
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception:
            info = {}
        rev_growth = info.get("revenueGrowth")  # decimal, e.g. 0.25
        rev_growth_pct = rev_growth * 100.0 if isinstance(rev_growth, (int, float)) else None
        return Fundamentals(
            symbol=symbol,
            source=self.source,
            ps_ttm=info.get("priceToSalesTrailing12Months"),
            revenue_growth_pct=rev_growth_pct,
            market_cap=info.get("marketCap"),
            sector=info.get("sector"),
            analyst_high=info.get("targetHighPrice"),
            analyst_low=info.get("targetLowPrice"),
            analyst_mean=info.get("targetMeanPrice"),
        )

    # --------------------------- option chains ------------------------------ #
    def get_chain(self, symbol: str, max_expiries: int = 4) -> OptionChain:
        t = yf.Ticker(symbol)
        spot, _ = self._last_price(t, symbol)
        try:
            expiries = list(t.options or [])
        except Exception:
            expiries = []
        by_expiry: dict[date, ExpiryChain] = {}
        today = date.today()
        for exp_str in expiries[:max_expiries]:
            try:
                exp = date.fromisoformat(exp_str)
            except ValueError:
                continue
            try:
                oc = t.option_chain(exp_str)
            except Exception:
                continue
            calls = self._clean(oc.calls)
            puts = self._clean(oc.puts)
            by_expiry[exp] = ExpiryChain(
                expiry=exp, dte=(exp - today).days, calls=calls, puts=puts
            )
        return OptionChain(
            symbol=symbol, spot=spot, as_of=datetime.now(tz=_UTC),
            source=self.source, is_delayed=True, by_expiry=by_expiry,
        )

    @staticmethod
    def _clean(df: pd.DataFrame) -> pd.DataFrame:
        """Keep the columns GEX/IV math needs; coerce numerics; drop junk rows."""
        cols = ["strike", "bid", "ask", "lastPrice", "volume",
                "openInterest", "impliedVolatility"]
        out = pd.DataFrame()
        for c in cols:
            out[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else pd.NA
        return out.dropna(subset=["strike"]).reset_index(drop=True)

    # ----------------------------- earnings --------------------------------- #
    def get_next_earnings(self, symbol: str) -> Optional[date]:
        """Next future earnings date from yfinance, or None. Best-effort across
        the two shapes yfinance has shipped (get_earnings_dates / calendar)."""
        t = yf.Ticker(symbol)
        today = date.today()
        try:
            ed = t.get_earnings_dates(limit=12)
            if ed is not None and not ed.empty:
                future = [d.date() for d in ed.index.to_pydatetime() if d.date() >= today]
                if future:
                    return min(future)
        except Exception:
            pass
        try:
            cal = t.calendar
            val = None
            if isinstance(cal, dict):
                val = cal.get("Earnings Date")
                if isinstance(val, (list, tuple)) and val:
                    val = val[0]
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"].iloc[0]
            if val is not None:
                d = pd.to_datetime(val).date()
                if d >= today:
                    return d
        except Exception:
            pass
        return None
