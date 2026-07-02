"""Central configuration: the $2,000 book rules, risk constants, and API keys.

Keys are loaded from a local `.env` via python-dotenv. They are NEVER printed,
logged, or committed — `get_key()` is the only accessor and it returns None when
a key is absent so the rest of the tool can degrade to its zero-key path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Load .env from the project root (one level above this package).
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:  # python-dotenv not installed yet — env vars still work.
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent


DATA_DIR = _PROJECT_ROOT / "data"
JOURNAL_DB = DATA_DIR / "journal.db"
MACRO_DATES_FILE = DATA_DIR / "fomc_cpi_dates.json"


# --------------------------------------------------------------------------- #
# Book rules — calibrated to a $2,000 account. Change BOOK_SIZE in .env to       #
# recalibrate every downstream dollar figure.                                   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BookRules:
    book_size: float = 2_000.0
    # Risk per trade as a fraction of equity. USER-CONFIGURED to 10% ($200 on a
    # $2k book); slider band 1%-20%. This is an aggressive profile chosen by the
    # user, well above the original 0.75% spec default. It is the amount lost if
    # stopped out, NOT the position size (which is further capped by buying power).
    default_risk_pct: float = 0.10
    min_risk_pct: float = 0.01
    max_risk_pct: float = 0.20
    # Hard caps, scaled proportionally to the new risk (see README "Risk profile").
    per_position_cap_pct: float = 0.10   # max loss on any single trade <= 10% ($200)
    portfolio_heat_cap_pct: float = 0.40  # total open risk across book <= 40% ($800, ~4 concurrent)
    # Halve the risk budget for any entry held across a binary print.
    binary_event_haircut: float = 0.5

    @property
    def default_risk_dollars(self) -> float:
        return self.book_size * self.default_risk_pct

    @property
    def per_position_cap_dollars(self) -> float:
        return self.book_size * self.per_position_cap_pct

    @property
    def portfolio_heat_cap_dollars(self) -> float:
        return self.book_size * self.portfolio_heat_cap_pct


def load_book_rules() -> BookRules:
    """Build BookRules, allowing BOOK_SIZE / RISK_PCT overrides from the env."""
    book = float(os.getenv("BOOK_SIZE", "2000"))
    risk = float(os.getenv("DEFAULT_RISK_PCT", "0.10"))
    return BookRules(book_size=book, default_risk_pct=risk)


# Continuously-compounded risk-free rate used by the local greeks / GEX math.
# A single scalar is plenty for short-dated swing horizons; override via env.
def risk_free_rate() -> float:
    return float(os.getenv("RISK_FREE_RATE", "0.043"))


# --------------------------------------------------------------------------- #
# Single-name GEX eligibility.                                                  #
# Per the spec, single-name GEX is only trustworthy for liquid mega-caps. Below #
# this market cap we still COMPUTE single-name GEX but label its walls "soft"   #
# and lean on index (SPX/QQQ) GEX as the real backdrop.                         #
# --------------------------------------------------------------------------- #
SINGLE_NAME_GEX_MIN_MARKET_CAP = float(
    os.getenv("SINGLE_NAME_GEX_MIN_MARKET_CAP", "200e9")
)

# Index symbols used as the market-regime backdrop layer.
INDEX_GEX_SYMBOLS = ("SPY", "QQQ")


# --------------------------------------------------------------------------- #
# API keys — all optional. Absence triggers the documented zero-key fallback.   #
# --------------------------------------------------------------------------- #
_KEY_ENV = {
    "finnhub": "FINNHUB_API_KEY",
    "flashalpha": "FLASHALPHA_API_KEY",
    "tradier": "TRADIER_API_KEY",
    "polygon": "POLYGON_API_KEY",
    "tiingo": "TIINGO_API_KEY",
}


def get_key(provider: str) -> str | None:
    """Return the API key for `provider`, or None if unset. Never logs the value."""
    env_name = _KEY_ENV.get(provider)
    if env_name is None:
        return None
    val = os.getenv(env_name)
    return val.strip() if val and val.strip() else None


def has_key(provider: str) -> bool:
    return get_key(provider) is not None


# Stage 0 liquidity gate thresholds. Deliberately conservative: below these,
# single-name options/GEX are too thin to mean anything (name becomes share-only).
@dataclass(frozen=True)
class LiquidityThresholds:
    min_near_strike_oi: int = 1_000        # OI "in the thousands" at near strikes
    max_rel_spread: float = 0.10           # (ask-bid)/mid at ATM, penny-to-few-cent
    min_daily_contract_volume: int = 500   # real daily volume across the chain
    near_strike_count: int = 6             # strikes either side of spot to inspect


LIQUIDITY = LiquidityThresholds()
