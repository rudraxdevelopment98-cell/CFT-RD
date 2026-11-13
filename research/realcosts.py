"""Re-run the research with real venue costs (research/costs.py).

    python -m research.realcosts

1. Each chosen sleeve under three cost scenarios, out of sample.
2. For every instrument, the best strategy once realistic costs are charged —
   does the original pick still win?
3. The equal-weight portfolio under realistic costs.
"""
from __future__ import annotations

import pandas as pd

from . import backtest, metrics
from .costs import SCENARIOS, cost_kwargs
from .lab import load, OOS_FRAC
from .strategies import REGISTRY

CONFIG = {"GOLD": "TrendEMA", "SILVER": "Bollinger", "OIL": "RSImeanrev",
          "BTC": "TrendEMA", "ETH": "TrendEMA"}
COLS = ["CAGR%", "Sharpe", "MaxDD%", "Trades"]


def oos_run(inst, strat, scenario):
    df = load(inst)
    split = int(len(df) * (1 - OOS_FRAC))
    pos = REGISTRY[strat](df)
    return backtest.run(df.iloc[split:], pos.iloc[split:], **cost_kwargs(inst, scenario))


def sleeves_by_scenario():
    rows = {}
    for inst, strat in CONFIG.items():
        for sc in SCENARIOS:
            m = oos_run(inst, strat, sc)["metrics"]
            rows[(f"{inst}/{strat}", sc)] = {k: m[k] for k in COLS}
    return pd.DataFrame(rows).T


def best_under_real_costs():
    out = {}
    for inst in CONFIG:
        scores = {s: oos_run(inst, s, "realistic")["metrics"] for s in REGISTRY}
        best = max(scores, key=lambda s: scores[s]["Sharpe"])
        df = load(inst)
        split = int(len(df) * (1 - OOS_FRAC))
        bh = metrics.buy_hold(df.iloc[split:])
        out[inst] = {"current": CONFIG[inst],
                     "current Sharpe": scores[CONFIG[inst]]["Sharpe"],
                     "best": best, "best Sharpe": scores[best]["Sharpe"],
                     "best CAGR%": scores[best]["CAGR%"],
                     "best MaxDD%": scores[best]["MaxDD%"],
                     "B&H Sharpe": bh["Sharpe"]}
    return pd.DataFrame(out).T


def portfolio(config, scenario):
    R = pd.DataFrame({f"{i}/{s}": oos_run(i, s, scenario)["returns"]
                      for i, s in config.items()}).fillna(0.0)
    port = R.mean(axis=1)                       # equal weight
    eq = 10_000 * (1 + port).cumprod()
    m = metrics.compute(eq, [], port)
    return {k: float(m[k]) for k in ["CAGR%", "Sharpe", "MaxDD%", "Calmar"]}, eq.iloc[-1]


def main():
    pd.set_option("display.width", 140)
    print("=" * 72 + "\n1. CHOSEN SLEEVES · out of sample · three cost scenarios\n" + "=" * 72)
    print(sleeves_by_scenario().to_string())

    print("\n" + "=" * 72 + "\n2. BEST STRATEGY PER INSTRUMENT once realistic costs are charged\n" + "=" * 72)
    print(best_under_real_costs().to_string())

    print("\n" + "=" * 72 + "\n3. EQUAL-WEIGHT PORTFOLIO\n" + "=" * 72)
    for sc in SCENARIOS:
        m, final = portfolio(CONFIG, sc)
        print(f"{sc:16s} {m}  ·  £10,000 -> £{final:,.0f}")


if __name__ == "__main__":
    main()
