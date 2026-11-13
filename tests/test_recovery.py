"""Crash recovery, fail-safe kill switch, and network backoff."""
import pytest

from bot import strategies
from bot.brokers import PaperBroker
from bot.database import Database
from bot.live import LiveTrader, Venue
from bot.retry import ResilientBroker, with_backoff
from bot.risk import RiskManager
from conftest import ohlcv

MARKET = {"name": "GOLD", "symbol": "GOLD", "strategy": "script"}


@pytest.fixture
def script():
    """A strategy whose next signal the test controls."""
    plan = {"sig": None, "stop": None}
    strategies.REGISTRY["script"] = lambda df: (plan["sig"], plan["stop"])
    yield plan
    strategies.REGISTRY.pop("script", None)


def _venue(db, broker=None, prices=(100,) * 30, notes=None):
    risk = RiskManager(per_trade_pct=0.1)
    risk.new_day(10_000)
    v = Venue("paper", broker or PaperBroker(cash=10_000), risk, [MARKET],
              fetch=lambda m: ohlcv(list(prices)), db=db,
              notify=(notes.append if notes is not None else None),
              retry_sleep=lambda s: None)
    return v


def test_restart_restores_position_cash_and_stop_from_db(tmp_path, script):
    path = str(tmp_path / "t.db")
    db = Database(path)
    v = _venue(db)
    script.update(sig="enter", stop=0.05)
    v.tick()
    assert "GOLD" in v.broker.positions
    cash_after_buy = v.broker.cash
    db.close()

    # --- simulated crash: brand-new process, empty broker, same database ---
    db2 = Database(path)
    script.update(sig=None, stop=None)
    v2 = _venue(db2)
    v2.restore()
    assert v2.broker.cash == pytest.approx(cash_after_buy)
    assert v2.broker.positions["GOLD"]["units"] > 0
    assert v2.engine.stops["GOLD"] == pytest.approx(v.engine.stops["GOLD"])


def test_close_after_restart_records_trade(tmp_path, script):
    db = Database(str(tmp_path / "t.db"))
    v = _venue(db)
    script.update(sig="enter", stop=None)
    v.tick()
    v2 = _venue(db, prices=(100,) * 29 + (120, 120))   # last closed bar = 120
    v2.restore()
    script.update(sig="exit")
    v2.tick()
    [t] = db.trades()
    assert t["market"] == "GOLD" and t["exit_price"] > t["entry_price"]
    assert t["pnl"] > 0 and t["commission"] > 0
    assert db.positions() == []


def test_unreadable_equity_blocks_new_trades(tmp_path, script):
    class NoEquity(PaperBroker):
        def equity(self, marks):
            raise ConnectionError("broker down")

    notes = []
    risk = RiskManager()
    risk.new_day(10_000)
    from bot.engine import Engine
    eng = Engine(NoEquity(), risk, [MARKET], notify=notes.append)
    script.update(sig="enter")
    eng.step(MARKET, ohlcv([100] * 30))
    assert eng.broker.positions == {}
    assert any("CRITICAL" in n for n in notes)


def test_backoff_retries_then_succeeds_with_growing_delays():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("slow")
        return "ok"

    assert with_backoff(flaky, attempts=4, base=1, sleep=sleeps.append) == "ok"
    assert sleeps == [1, 2]


def test_backoff_gives_up_after_attempts():
    with pytest.raises(TimeoutError):
        with_backoff(lambda: (_ for _ in ()).throw(TimeoutError()), attempts=3,
                     sleep=lambda s: None)


def test_resilient_broker_retries_reads_but_never_orders():
    class Flaky:
        def __init__(self):
            self.eq_calls = self.buy_calls = 0

        def equity(self, marks):
            self.eq_calls += 1
            if self.eq_calls == 1:
                raise TimeoutError()
            return 500

        def buy(self, *a, **k):
            self.buy_calls += 1
            raise TimeoutError("order timed out")

    inner = Flaky()
    b = ResilientBroker(inner, sleep=lambda s: None)
    assert b.equity({}) == 500 and inner.eq_calls == 2
    with pytest.raises(TimeoutError):
        b.buy("X", 1, 1)
    assert inner.buy_calls == 1                         # an order is sent once only


def test_trader_writes_heartbeats_and_alerts_on_crash(tmp_path, script):
    db = Database(str(tmp_path / "t.db"))

    class Boom(Venue):
        def tick(self, ts=None):
            raise RuntimeError("kaboom")

    notes = []
    v = Boom("paper", PaperBroker(), RiskManager(), [MARKET], fetch=None, db=db)
    LiveTrader([v], period_s=120, notify=notes.append, sleep=lambda s: None,
               db=db, mode="paperlive", heartbeat_s=60).run(max_cycles=2)
    statuses = [r["status"] for r in db._rows("SELECT status FROM heartbeats ORDER BY id")]
    assert statuses == ["starting", "error", "idle", "error", "stopped"]
    assert db.last_error()["error_message"].endswith("kaboom")
    assert any(n.startswith("CRITICAL") for n in notes)
    assert db.get_kv("run")["mode"] == "paperlive"
