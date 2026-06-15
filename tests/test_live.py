"""The live wiring: closed-bar discipline, per-market isolation, persistence."""
import pytest

from bot import strategies
from bot.live import Venue, LiveTrader
from bot.risk import RiskManager
from bot.state import StateStore
from conftest import ohlcv, FakeBroker


@pytest.fixture
def record_strategy():
    """A strategy that records the window length it was handed, never trades."""
    seen = []
    strategies.REGISTRY["record"] = lambda df: (seen.append(len(df)) or (None, None))
    yield seen
    strategies.REGISTRY.pop("record", None)


def _venue(broker, markets, fetch, **kw):
    risk = RiskManager()
    risk.new_day(broker.equity({}))
    return Venue("test", broker, risk, markets, fetch=fetch,
                 notify=lambda m: None, **kw)


def test_tick_drops_the_forming_bar(record_strategy):
    market = {"name": "X", "symbol": "X", "strategy": "record"}
    v = _venue(FakeBroker(), [market], fetch=lambda m: ohlcv([100] * 10))
    v.tick()
    assert record_strategy == [9]                  # 10 fetched, last (forming) dropped


def test_use_closed_bar_false_keeps_all_bars(record_strategy):
    market = {"name": "X", "symbol": "X", "strategy": "record"}
    v = _venue(FakeBroker(), [market], fetch=lambda m: ohlcv([100] * 10),
               use_closed_bar=False)
    v.tick()
    assert record_strategy == [10]


def test_one_markets_data_error_does_not_stop_others(record_strategy):
    good = {"name": "G", "symbol": "G", "strategy": "record"}
    bad = {"name": "B", "symbol": "B", "strategy": "record"}

    def fetch(m):
        if m["symbol"] == "B":
            raise RuntimeError("feed down")
        return ohlcv([100] * 10)

    v = _venue(FakeBroker(), [bad, good], fetch=fetch)
    v.tick()                                        # must not raise
    assert record_strategy == [9]                   # good market still processed


def test_tick_persists_risk_state(tmp_path, record_strategy):
    market = {"name": "X", "symbol": "X", "strategy": "record"}
    store = StateStore(str(tmp_path / "s.json"))
    v = _venue(FakeBroker(), [market], fetch=lambda m: ohlcv([100] * 10),
               state=store)
    v.tick()
    assert "risk" in store.load()


def test_restore_reapplies_halt(tmp_path, record_strategy):
    market = {"name": "X", "symbol": "X", "strategy": "record"}
    store = StateStore(str(tmp_path / "s.json"))
    v = _venue(FakeBroker(), [market], fetch=lambda m: ohlcv([100] * 10),
               state=store)
    v.risk.halted = True
    v.persist()

    v2 = _venue(FakeBroker(), [market], fetch=lambda m: ohlcv([100] * 10),
                state=store)
    v2.restore()
    assert v2.risk.halted is True


def test_livetrader_runs_fixed_cycles_and_sleeps_between(record_strategy):
    market = {"name": "X", "symbol": "X", "strategy": "record"}
    v = _venue(FakeBroker(), [market], fetch=lambda m: ohlcv([100] * 10))
    sleeps = []
    LiveTrader([v], period_s=60, sleep=sleeps.append).run(max_cycles=3)
    assert len(record_strategy) == 3                # 3 ticks
    assert sleeps == [60, 60]                        # slept between, not after last
