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

    # (a) equal-weight across sleeves
    eq_w = R.mul(1.0 / R.shape[1]).sum(axis=1)

    # (b) inverse-volatility weighting: size each sleeve by 1 / its trailing
    # 60-day vol (shifted 1 day to avoid look-ahead), renormalised daily. This
    # equalises *risk* across sleeves, so crypto's big swings stop dominating
    # the book and a fragile sleeve can't sink it — directly addresses the
    # "every sleeve carries different risk" finding from the walk-forward.
    vol = R.rolling(60).std().shift(1)
    inv = (1.0 / vol).replace([float("inf")], 0.0)
    w = inv.div(inv.sum(axis=1), axis=0).fillna(1.0 / R.shape[1])
    iv_port = (R * w).sum(axis=1)

    def eqcurve(r):
        return 10_000 * (1 + r).cumprod()

    eq_eq, iv_eq = eqcurve(eq_w), eqcurve(iv_port)

    # equal-weight buy & hold of the same instruments, as the honest benchmark
    BH = pd.DataFrame(bh).reindex(R.index).fillna(0.0)
    bh_port = BH.mul(1.0 / BH.shape[1]).sum(axis=1)
    bh_eq = eqcurve(bh_port)

    print("Correlation of sleeve daily returns (low = good diversification):")
    print(R.corr().round(2).to_string())

    print(f"\n{'='*78}\nPORTFOLIO comparison (OOS {R.index[0].date()} -> "
          f"{R.index[-1].date()})\n{'='*78}")
    table = pd.DataFrame({
        "Equal-weight strategy": metrics.compute(eq_eq, [], eq_w),
        "Inverse-vol strategy": metrics.compute(iv_eq, [], iv_port),
        "Equal-weight Buy & Hold": metrics.compute(bh_eq, [], bh_port),
    }).T
    print(table[["CAGR%", "Sharpe", "Sortino", "MaxDD%", "Calmar", "Expo%"]].to_string())
    print(f"\nFinal equity on £10,000:  equal-wt £{eq_eq.iloc[-1]:,.0f}  ·  "
          f"inverse-vol £{iv_eq.iloc[-1]:,.0f}  ·  buy&hold £{bh_eq.iloc[-1]:,.0f}")
    print("\nAvg sleeve weights under inverse-vol (risk parity):")
    print((w.mean() * 100).round(1).astype(str).add("%").to_string())


if __name__ == "__main__":
    main()
