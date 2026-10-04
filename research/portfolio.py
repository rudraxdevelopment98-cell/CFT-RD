"""Portfolio backtest — the real 'algo'.

No single strategy wins everywhere. The edge is combining a handful of
*independent* instrument+strategy pairs so their drawdowns don't line up. This
runs a chosen config, equal-risk-weights the sleeves, and reports the blended
result vs an equal-weight buy & hold.

    python -m research.portfolio
"""
from __future__ import annotations

import os
import pandas as pd

from . import backtest, metrics
from .lab import load, OOS_FRAC, CRYPTO
from .strategies import REGISTRY

# Selected by research/lab.py on OUT-OF-SAMPLE Sharpe + tolerable drawdown.
# FX majors were dropped — no reliable edge (markets too efficient).
CONFIG = {
    "GOLD":   "TrendEMA",     # trend: gold trends cleanly
    "SILVER": "Bollinger",    # mean-reversion: silver whips around a mean
    "OIL":    "RSImeanrev",   # mean-reversion: oil bounces off oversold
    "BTC":    "TrendEMA",     # trend, small size (big drawdowns)
    "ETH":    "TrendEMA",     # trend, small size
}


def sleeve_returns(inst, strat):
    df = load(inst)
    split = int(len(df) * (1 - OOS_FRAC))
    cost = 0.0010 if inst in CRYPTO else 0.0005
    pos = REGISTRY[strat](df)
    res = backtest.run(df.iloc[split:], pos.iloc[split:], cost_per_side=cost)
    return res["returns"], df.iloc[split:]


def main():
    rets, bh = {}, {}
    for inst, strat in CONFIG.items():
        r, oos = sleeve_returns(inst, strat)
        rets[f"{inst}/{strat}"] = r
        bh[inst] = oos.close.pct_change().fillna(0.0)

    R = pd.DataFrame(rets).dropna(how="all").fillna(0.0)
    w = 1.0 / R.shape[1]                       # equal weight across sleeves
    port = R.mul(w).sum(axis=1)
    equity = 10_000 * (1 + port).cumprod()

    # equal-weight buy & hold of the same instruments, as the honest benchmark
    BH = pd.DataFrame(bh).reindex(R.index).fillna(0.0)
    bh_port = BH.mul(1.0 / BH.shape[1]).sum(axis=1)
    bh_eq = 10_000 * (1 + bh_port).cumprod()

    print("Correlation of sleeve daily returns (low = good diversification):")
    print(R.corr().round(2).to_string())

    pm = metrics.compute(equity, [], port)
    bm = metrics.compute(bh_eq, [], bh_port)
    print(f"\n{'='*70}\nPORTFOLIO (equal-weight, OOS {R.index[0].date()} -> "
          f"{R.index[-1].date()})\n{'='*70}")
    table = pd.DataFrame({"5-sleeve strategy portfolio": pm,
                          "Equal-weight Buy & Hold": bm}).T
    print(table[["CAGR%", "Sharpe", "Sortino", "MaxDD%", "Calmar", "Expo%"]].to_string())
    print(f"\nFinal equity on £10,000 start:  strategy £{equity.iloc[-1]:,.0f}  "
          f"vs  buy&hold £{bh_eq.iloc[-1]:,.0f}")


if __name__ == "__main__":
    main()
