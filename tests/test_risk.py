"""The risk manager is the kill switch. If it's wrong, the account is at risk."""
from datetime import date

from bot.risk import RiskManager


def test_stake_is_per_trade_pct_of_equity():
    r = RiskManager(per_trade_pct=0.02)
    assert r.stake(10_000) == 200


def test_daily_limit_halts_at_threshold_and_stays_halted():
    r = RiskManager(daily_loss_limit_pct=0.05)
    r.new_day(10_000)
    assert r.check_daily_limit(9_600) is True          # -4% ok
    assert r.check_daily_limit(9_500) is False         # -5% trips
    assert r.halted is True
    assert r.check_daily_limit(10_000) is False         # stays halted within the day


def test_can_open_respects_halt_and_max_open():
    r = RiskManager(max_open=3)
    r.new_day(10_000)
    assert r.can_open(2) is True
    assert r.can_open(3) is False                       # at cap
    r.halted = True
    assert r.can_open(0) is False                       # halted overrides


def test_new_day_resets_and_stamps_today():
    r = RiskManager()
    r.halted = True
    r.new_day(5_000)
    assert r.halted is False
    assert r.day_start_equity == 5_000
    assert r.day == date.today()


def test_maybe_new_day_rolls_over_only_on_a_new_date():
    r = RiskManager()
    r.new_day(10_000)
    assert r.maybe_new_day(12_000) is False             # same day, no reset
    assert r.day_start_equity == 10_000
    r.day = date(2000, 1, 1)                             # pretend it's stale
    assert r.maybe_new_day(12_000) is True
    assert r.day_start_equity == 12_000 and r.day == date.today()
