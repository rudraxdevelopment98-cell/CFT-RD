"""Cost model and research-matched sizing."""
import pytest

from conftest import ohlcv
from research import backtest
from research.costs import SCENARIOS, cost_kwargs


def test_holding_cost_is_charged_only_while_in_a_position():
    df = ohlcv([100.0] * 253)                          # flat price, one year
    always = backtest.run(df, df.close * 0 + 1, cost_per_side=0,
                          hold_cost_annual=0.0625, bars_per_year=252)
    never = backtest.run(df, df.close * 0, cost_per_side=0,
                         hold_cost_annual=0.0625, bars_per_year=252)
    lost = 1 - always["equity"].iloc[-1] / 10_000
    assert lost == pytest.approx(0.0625, abs=0.003)     # ~ one year of funding
    assert never["equity"].iloc[-1] == 10_000


def test_every_scenario_covers_every_traded_instrument():
    for sc in SCENARIOS.values():
        assert set(sc) == {"GOLD", "SILVER", "OIL", "BTC", "ETH"}
    k = cost_kwargs("BTC", "realistic")
    assert k["hold_cost_annual"] == 0 and k["bars_per_year"] == 365


def test_sized_risk_matches_research_equal_weight():
    from run import sized_risk
    r = sized_risk(5, daily_loss_limit_pct=0.05)
    assert r.stake(10_000) == pytest.approx(2_000)       # 1/5 of equity
    assert r.can_open(4) and not r.can_open(5)
