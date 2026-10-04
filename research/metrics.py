"""Honest performance metrics. Win rate alone is meaningless — these are the
numbers that decide whether a strategy actually has edge.

Everything is computed from a daily equity curve + list of per-trade returns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _cagr(equity: pd.Series) -> float:
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    growth = equity.iloc[-1] / equity.iloc[0]
    if growth <= 0:
        return -1.0
    return growth ** (1 / years) - 1


def compute(equity: pd.Series, trades: list[float], bar_returns: pd.Series) -> dict:
    """equity: daily account value. trades: per-trade return fractions.
    bar_returns: the strategy's daily return series (for Sharpe/Sortino)."""
    total_ret = equity.iloc[-1] / equity.iloc[0] - 1
    dd = (equity / equity.cummax() - 1).min()

    r = bar_returns.dropna()
    ann_vol = r.std() * np.sqrt(TRADING_DAYS)
    ann_ret = r.mean() * TRADING_DAYS
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    downside = r[r < 0].std() * np.sqrt(TRADING_DAYS)
    sortino = ann_ret / downside if downside > 0 else 0.0
    cagr = _cagr(equity)
    calmar = cagr / abs(dd) if dd < 0 else 0.0

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    n = len(trades)
    win_rate = len(wins) / n if n else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")
    expectancy = np.mean(trades) if trades else 0.0  # avg return per trade

    # fraction of days the strategy was actually in the market
    exposure = float((bar_returns != 0).mean())

    return {
        "CAGR%": round(cagr * 100, 1),
        "Total%": round(total_ret * 100, 1),
        "MaxDD%": round(dd * 100, 1),
        "Sharpe": round(sharpe, 2),
        "Sortino": round(sortino, 2),
        "Calmar": round(calmar, 2),
        "Trades": n,
        "Win%": round(win_rate * 100, 1),
        "PF": round(pf, 2) if pf != float("inf") else 99.0,
        "Expect%": round(expectancy * 100, 2),
        "AvgWin%": round(avg_win * 100, 2),
        "AvgLoss%": round(avg_loss * 100, 2),
        "Expo%": round(exposure * 100, 0),
    }


def buy_hold(df: pd.DataFrame) -> dict:
    eq = df.close / df.close.iloc[0]
    r = df.close.pct_change()
    return compute(eq, [df.close.iloc[-1] / df.close.iloc[0] - 1], r)
