from swingdesk import journal


def _log(db, **kw):
    base = dict(ticker="AAPL", setup_type="breakout", direction="long",
                instrument="shares", regime_tag="negative", entry=100, stop=98,
                target=110, size=7, risk_dollars=15.0, outcome="open", pnl=None)
    base.update(kw)
    return journal.log_trade(base, db_path=db)


def test_log_and_list(tmp_path):
    db = tmp_path / "j.db"
    tid = _log(db)
    assert tid == 1
    df = journal.list_trades(db)
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AAPL"


def test_open_risk_sums_only_open(tmp_path):
    db = tmp_path / "j.db"
    _log(db, risk_dollars=15.0, outcome="open")
    _log(db, risk_dollars=20.0, outcome="open")
    _log(db, risk_dollars=99.0, outcome="win", pnl=30)  # closed -> excluded
    assert journal.open_risk_dollars(db) == 35.0


def test_expectancy_by_bucket(tmp_path):
    db = tmp_path / "j.db"
    _log(db, setup_type="breakout", outcome="win", pnl=30.0)
    _log(db, setup_type="breakout", outcome="loss", pnl=-10.0)
    exp = journal.expectancy_by_bucket(db)
    row = exp[exp["setup_type"] == "breakout"].iloc[0]
    assert row["n"] == 2
    assert row["win_rate"] == 0.5
    assert row["expectancy"] == 10.0   # 0.5*30 - 0.5*10
    assert not row["significant"]      # under 30 trades


def test_open_position_sectors(tmp_path):
    db = tmp_path / "j.db"
    _log(db, ticker="AAPL", outcome="open")
    _log(db, ticker="XOM", outcome="win", pnl=5)  # closed -> excluded
    sectors = journal.open_position_sectors(lambda t: "Technology" if t == "AAPL" else "Energy", db)
    assert sectors == {"AAPL": "Technology"}
