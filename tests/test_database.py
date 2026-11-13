"""SQLite layer: the record of every position and trade."""
import sqlite3

import pytest

from bot.database import Database, DbStateStore
from bot.risk import RiskManager


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    yield d
    d.close()


def _open(db, **kw):
    args = dict(venue="paper", symbol="GOLD", market="GOLD", strategy="trend",
                size=2.0, cost=200.0, entry_price=100.0, stop_loss=95.0, cash=9_800)
    args.update(kw)
    db.open_position(**args)


def test_open_position_writes_row_and_cash(db):
    _open(db)
    [p] = db.positions()
    assert p["symbol"] == "GOLD" and p["stop_loss"] == 95.0 and p["last_price"] == 100.0
    assert db.get_kv("paper.cash") == 9_800


def test_close_moves_position_into_trades_atomically(db):
    _open(db)
    tid = db.close_position(venue="paper", symbol="GOLD", exit_price=110.0,
                            reason="exit signal", commission=0.4, cash=10_020)
    assert db.positions() == []
    [t] = db.trades()
    assert t["id"] == tid and t["market"] == "GOLD" and t["strategy"] == "trend"
    assert t["pnl"] == pytest.approx(20.0)            # (110-100) * 2, computed
    assert t["pnl_pct"] == pytest.approx(0.10)
    assert t["entry_time"] is not None and t["reason"] == "exit signal"
    assert db.get_kv("paper.cash") == 10_020


def test_broker_reported_pnl_wins_over_computed(db):
    _open(db)
    db.close_position(venue="paper", symbol="GOLD", exit_price=110.0,
                      reason="x", pnl=17.5, pnl_pct=0.0875)
    assert db.trades()[0]["pnl"] == 17.5


def test_failed_transaction_rolls_back_everything(db):
    _open(db)
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("DELETE FROM positions WHERE symbol='GOLD'")
            raise RuntimeError("crash mid-write")
    assert len(db.positions()) == 1                    # delete was undone


def test_trade_stats_and_win_rate(db):
    for sym, exitp in [("A", 110), ("B", 90), ("C", 120)]:
        _open(db, symbol=sym, market=sym)
        db.close_position(venue="paper", symbol=sym, exit_price=exitp, reason="x")
    s = db.trade_stats()
    assert s["trades"] == 3 and s["wins"] == 2
    assert s["win_rate"] == pytest.approx(2 / 3)
    assert s["realized_pnl"] == pytest.approx(20 - 20 + 40)


def test_equity_series_sums_venues_per_cycle(db):
    db.snapshot_equity("crypto", 1000, timestamp="2026-01-01T00:00:00+00:00")
    db.snapshot_equity("ig", 500, timestamp="2026-01-01T00:00:00+00:00")
    db.snapshot_equity("crypto", 1100, timestamp="2026-01-02T00:00:00+00:00")
    db.snapshot_equity("ig", 450, timestamp="2026-01-02T00:00:00+00:00")
    assert [r["equity"] for r in db.equity_series()] == [1500, 1550]
    # a repeated snapshot for the same venue and cycle replaces, never adds
    db.snapshot_equity("ig", 460, timestamp="2026-01-02T00:00:00+00:00")
    assert [r["equity"] for r in db.equity_series()] == [1500, 1560]


def test_heartbeat_and_last_error(db):
    db.heartbeat("ok", 10)
    db.heartbeat("error", 20, "IG timeout")
    db.heartbeat("idle", 30)
    assert db.last_heartbeat()["status"] == "idle"
    assert db.last_error()["error_message"] == "IG timeout"


def test_update_marks(db):
    _open(db)
    db.update_marks({"GOLD": 104.5, "NOT_HELD": 1})
    assert db.positions()[0]["last_price"] == 104.5


def test_readonly_connection_cannot_write(db, tmp_path):
    _open(db)
    ro = Database(db.path, readonly=True)
    try:
        assert len(ro.positions()) == 1
        with pytest.raises(sqlite3.OperationalError):
            ro.set_kv("x", 1)
    finally:
        ro.close()


def test_db_state_store_round_trips_risk_and_paper_book(db):
    from bot.brokers import PaperBroker
    _open(db)
    store = DbStateStore(db, "paper")
    risk = RiskManager()
    risk.new_day(10_000)
    risk.halted = True
    store.persist(risk=risk, stops={"GOLD": 97.0})

    fresh = RiskManager()
    assert store.restore_risk(fresh) and fresh.halted
    broker = PaperBroker(cash=10_000)
    assert store.restore_broker(broker)
    assert broker.cash == 9_800
    assert broker.positions["GOLD"]["stop"] == 97.0
    assert store.load()["stops"] == {"GOLD": 97.0}
