"""State persistence keeps a restart from re-arming a tripped kill switch."""
from datetime import date

from bot.risk import RiskManager
from bot.state import StateStore


def test_save_load_round_trip(tmp_path):
    s = StateStore(str(tmp_path / "state.json"))
    s.save({"a": 1, "b": [2, 3]})
    assert s.load() == {"a": 1, "b": [2, 3]}


def test_load_missing_file_returns_empty(tmp_path):
    assert StateStore(str(tmp_path / "nope.json")).load() == {}


def test_persist_then_restore_keeps_halt_state_for_today(tmp_path):
    s = StateStore(str(tmp_path / "state.json"))
    risk = RiskManager()
    risk.new_day(10_000)
    risk.halted = True
    s.persist(risk=risk, stops={"X": 95})

    fresh = RiskManager()
    assert s.restore_risk(fresh) is True
    assert fresh.halted is True
    assert fresh.day_start_equity == 10_000
    assert s.load()["stops"] == {"X": 95}


def test_paper_broker_persist_restore_round_trip(tmp_path):
    from bot.brokers import PaperBroker
    s = StateStore(str(tmp_path / "state.json"))
    b = PaperBroker(cash=10_000)
    b.buy("BTC", 2_000, 100, stop=95)
    s.persist(broker=b)

    fresh = PaperBroker(cash=10_000)
    assert s.restore_broker(fresh) is True
    assert fresh.cash == b.cash
    assert "BTC" in fresh.positions
    assert fresh.positions["BTC"]["stop"] == 95


def test_restore_ignores_stale_day(tmp_path):
    s = StateStore(str(tmp_path / "state.json"))
    risk = RiskManager()
    risk.new_day(10_000)
    risk.halted = True
    risk.day = date(2000, 1, 1)                    # yesterday (and then some)
    s.persist(risk=risk)

    fresh = RiskManager()
    assert s.restore_risk(fresh) is False          # new day -> don't restore halt
    assert fresh.halted is False


def test_save_is_atomic_no_partial_file_on_failure(tmp_path):
    s = StateStore(str(tmp_path / "state.json"))
    s.save({"ok": 1})

    class Unserializable:
        pass

    try:
        s.save({"bad": Unserializable()})
    except TypeError:
        pass
    assert s.load() == {"ok": 1}                    # original intact
    assert not list(tmp_path.glob("*.tmp"))         # temp file cleaned up
