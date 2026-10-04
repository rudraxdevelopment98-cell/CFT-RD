"""Vectorized long/flat backtester. Fees + slippage charged on every position
change, so the numbers aren't fantasy. Returns equity curve, per-trade returns
and the daily strategy-return series the metrics need.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import metrics


def run(df: pd.DataFrame, position: pd.Series, cost_per_side=0.0005,
        capital=10_000) -> dict:
    """position: target 0/1 at the decision bar. Executed on the NEXT bar
    (shift 1). cost_per_side: fraction charged on entry and on exit."""
    pos = position.shift(1).fillna(0.0).clip(0, 1)
    ret = df.close.pct_change().fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * cost_per_side
    strat_ret = pos * ret - cost
    equity = capital * (1 + strat_ret).cumprod()

    # segment contiguous holds into trades
    trades, in_pos, acc = [], False, 1.0
    p = pos.values
    sr = strat_ret.values
    for i in range(len(p)):
        if p[i] > 0 and not in_pos:
            in_pos, acc = True, 1.0
        if in_pos:
            acc *= (1 + sr[i])
        if in_pos and (i + 1 >= len(p) or p[i + 1] == 0):
            trades.append(acc - 1.0)
            in_pos = False

    m = metrics.compute(equity, trades, strat_ret)
    return {"equity": equity, "trades": trades, "returns": strat_ret, "metrics": m}
