"""The engine glues signal -> risk gate -> execution. Test the gates fire."""
import pytest

from bot import strategies
from bot.engine import Engine
from bot.risk import RiskManager
from conftest import ohlcv, FakeBroker


@pytest.fixture
def fake_strategies():
    """Inject deterministic strategies into the shared REGISTRY, then clean up."""
    strategies.REGISTRY["always_enter"] = lambda df: ("enter", None)
    strategies.REGISTRY["enter_stop"] = lambda df: ("enter", 0.05)
    strategies.REGISTRY["always_exit"] = lambda df: ("exit", None)
    strategies.REGISTRY["hold"] = lambda df: (None, None)
    yield
    for k in ("always_enter", "enter_stop", "always_exit", "hold"):
        strategies.REGISTRY.pop(k, None)


def _engine(broker, **risk_kw):
    risk = RiskManager(**risk_kw)
    risk.new_day(broker.equity({}))
    return Engine(broker, risk, [], notify=lambda m: None), risk


def test_enter_signal_opens_a_position_sized_by_risk(fake_strategies):
    b = FakeBroker(cash=10_000)
    eng, _ = _engine(b, per_trade_pct=0.02)
    eng.step({"name": "X", "symbol": "X", "strategy": "always_enter"},
             ohlcv([100] * 5))
    assert b.position("X") is not None
    assert b.position("X")["cost"] == pytest.approx(200)   # 2% of 10k


def test_enter_with_stop_pct_sets_a_stop_below_price(fake_strategies):
    b = FakeBroker()
    eng, _ = _engine(b)
    eng.step({"name": "X", "symbol": "X", "strategy": "enter_stop"},
             ohlcv([100] * 5))
    assert b.position("X")["stop"] == pytest.approx(95)     # 100 * (1 - 0.05)


def test_exit_signal_closes_open_position(fake_strategies):
    b = FakeBroker()
    eng, _ = _engine(b)
    b.buy("X", 200, 100)
    eng.step({"name": "X", "symbol": "X", "strategy": "always_exit"},
             ohlcv([100] * 5))
    assert b.position("X") is None


def test_stop_loss_closes_when_price_breaches_stop(fake_strategies):
    b = FakeBroker()
    eng, _ = _engine(b)
    b.buy("X", 200, 100, stop=95)
    eng.step({"name": "X", "symbol": "X", "strategy": "hold"},
             ohlcv([94] * 5))                               # below the stop
    assert b.position("X") is None
    assert b.orders[-1][0] == "sell"


def test_daily_halt_blocks_new_entries_and_flattens(fake_strategies):
    b = FakeBroker(cash=10_000)
    eng, risk = _engine(b, daily_loss_limit_pct=0.05)
    b.buy("X", 200, 100)
    risk.halted = True                                      # simulate tripped switch
    eng.step({"name": "X", "symbol": "X", "strategy": "always_enter"},
             ohlcv([100] * 5))
    assert b.position("X") is None                          # flattened on halt


def test_max_open_caps_concurrent_positions(fake_strategies):
    b = FakeBroker()
    eng, _ = _engine(b, max_open=1)
    b.buy("A", 200, 100)                                    # already at the cap
    eng.step({"name": "B", "symbol": "B", "strategy": "always_enter"},
             ohlcv([100] * 5))
    assert b.position("B") is None
