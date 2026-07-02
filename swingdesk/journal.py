"""SQLite journal + per-setup expectancy tracker.

Logs every trade with its thesis, regime tag, levels, sizing, implied vs realized
move, outcome, P/L, and the pre-mortem text. Expectancy is computed per setup
bucket so the user can see which setups are positive vs negative.

Small samples are treated as DIRECTIONAL ONLY: the trade count is shown next to
every expectancy figure and anything under ~30 trades is labeled "not yet
significant."
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import JOURNAL_DB

SIGNIFICANCE_MIN_TRADES = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    ticker            TEXT NOT NULL,
    setup_type        TEXT,
    direction         TEXT,
    instrument        TEXT,
    regime_tag        TEXT,
    entry             REAL,
    stop              REAL,
    target            REAL,
    size              REAL,
    risk_dollars      REAL,
    implied_move      REAL,
    realized_move     REAL,
    outcome           TEXT,        -- 'win' | 'loss' | 'scratch' | 'open'
    pnl               REAL,
    premortem_bear    TEXT,
    premortem_invalidation TEXT,
    premortem_base_rate    TEXT
);
"""

_FIELDS = [
    "ticker", "setup_type", "direction", "instrument", "regime_tag",
    "entry", "stop", "target", "size", "risk_dollars", "implied_move",
    "realized_move", "outcome", "pnl",
    "premortem_bear", "premortem_invalidation", "premortem_base_rate",
]


def connect(db_path: Path = JOURNAL_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def init_db(db_path: Path = JOURNAL_DB) -> sqlite3.Connection:
    """Create the trades table if needed. Idempotent."""
    con = connect(db_path)
    con.executescript(_SCHEMA)
    con.commit()
    return con


def log_trade(trade: dict, db_path: Path = JOURNAL_DB) -> int:
    """Insert one trade. Unknown keys are ignored; missing keys default to NULL."""
    con = init_db(db_path)
    row = {k: trade.get(k) for k in _FIELDS}
    row["ts"] = trade.get("ts") or datetime.now(tz=timezone.utc).isoformat()
    cols = ["ts"] + _FIELDS
    placeholders = ", ".join("?" for _ in cols)
    cur = con.execute(
        f"INSERT INTO trades ({', '.join(cols)}) VALUES ({placeholders})",
        [row[c] for c in cols],
    )
    con.commit()
    new_id = cur.lastrowid
    con.close()
    return new_id


def list_trades(db_path: Path = JOURNAL_DB) -> pd.DataFrame:
    con = init_db(db_path)
    df = pd.read_sql_query("SELECT * FROM trades ORDER BY ts DESC", con)
    con.close()
    return df


def open_position_sectors(
    sector_lookup, db_path: Path = JOURNAL_DB
) -> dict[str, str]:
    """Map {ticker: sector} for currently-open trades, for the correlation check.
    `sector_lookup` is a callable ticker -> sector|None (e.g. provider/fundamentals).
    """
    df = list_trades(db_path)
    if df.empty:
        return {}
    open_df = df[df["outcome"].fillna("open") == "open"]
    out: dict[str, str] = {}
    for tkr in open_df["ticker"].unique():
        try:
            sec = sector_lookup(tkr)
        except Exception:
            sec = None
        if sec:
            out[tkr] = sec
    return out


def open_risk_dollars(db_path: Path = JOURNAL_DB) -> float:
    """Sum of risk_dollars across open trades — feeds the portfolio heat cap."""
    df = list_trades(db_path)
    if df.empty:
        return 0.0
    open_df = df[df["outcome"].fillna("open") == "open"]
    return float(pd.to_numeric(open_df["risk_dollars"], errors="coerce").fillna(0).sum())


def expectancy_by_bucket(db_path: Path = JOURNAL_DB) -> pd.DataFrame:
    """Per setup_type: n, win_rate, avg_win, avg_loss, expectancy, significance.

    expectancy = win_rate*avg_win - loss_rate*avg_loss  (avg_loss as a positive #)
    """
    df = list_trades(db_path)
    cols = ["setup_type", "n", "wins", "losses", "win_rate", "avg_win",
            "avg_loss", "expectancy", "significant"]
    if df.empty:
        return pd.DataFrame(columns=cols)

    closed = df[df["outcome"].isin(["win", "loss", "scratch"])].copy()
    closed["pnl"] = pd.to_numeric(closed["pnl"], errors="coerce")
    if closed.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    for setup, g in closed.groupby(closed["setup_type"].fillna("(unlabeled)")):
        n = len(g)
        wins = g[g["outcome"] == "win"]
        losses = g[g["outcome"] == "loss"]
        nw, nl = len(wins), len(losses)
        win_rate = nw / n if n else 0.0
        loss_rate = nl / n if n else 0.0
        avg_win = float(wins["pnl"].mean()) if nw else 0.0
        avg_loss = float(losses["pnl"].abs().mean()) if nl else 0.0
        expectancy = win_rate * avg_win - loss_rate * avg_loss
        rows.append({
            "setup_type": setup, "n": n, "wins": nw, "losses": nl,
            "win_rate": round(win_rate, 3), "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2), "expectancy": round(expectancy, 2),
            "significant": n >= SIGNIFICANCE_MIN_TRADES,
        })
    return pd.DataFrame(rows, columns=cols).sort_values("expectancy", ascending=False).reset_index(drop=True)
