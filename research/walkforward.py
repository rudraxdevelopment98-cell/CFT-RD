"""Walk-forward & parameter-robustness checks — the "is this edge real or luck?"
stage.

Two honest stress tests:

  1. YEAR-BY-YEAR STABILITY: the chosen strategy (fixed params) is scored on
     each calendar year separately. A real edge shows up in most years, not one
     lucky window. One great year hiding four poor ones = not tradable.

  2. PARAMETER ROBUSTNESS: sweep each strategy's main parameters and print the
     out-of-sample Sharpe surface. We want a broad PLATEAU of good values — if
     only one exact setting works and its neighbours fail, it's curve-fit and
     will not survive live.

    python -m research.walkforward
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest
from .lab import load, OOS_FRAC, CRYPTO
from .strategies import trend_ema, bollinger_meanrev, rsi_meanrev

CONFIG = {
    "GOLD":   ("TrendEMA", trend_ema),
    "SILVER": ("Bollinger", bollinger_meanrev),
    "OIL":    ("RSImeanrev", rsi_meanrev),
    "BTC":    ("TrendEMA", trend_ema),
    "ETH":    ("TrendEMA", trend_ema),
}


def cost_of(inst):
    return 0.0010 if inst in CRYPTO else 0.0005


def _oos_sharpe(inst, pos):
    df = load(inst)
    split = int(len(df) * (1 - OOS_FRAC))
    res = backtest.run(df.iloc[split:], pos.iloc[split:], cost_per_side=cost_of(inst))
    return res["metrics"]["Sharpe"], res["metrics"]["CAGR%"], res["metrics"]["MaxDD%"]


# --------------------------------------------------------------------------- #
# 1. Year-by-year stability
# --------------------------------------------------------------------------- #
def stability():
    print("=" * 78)
    print("YEAR-BY-YEAR  ·  total return % of each chosen strategy (fixed params)")
    print("=" * 78)
    rows = {}
    for inst, (name, fn) in CONFIG.items():
        df = load(inst)
        pos = fn(df)                         # signals on full history (warmup safe)
        cost = cost_of(inst)
        per_year = {}
        for yr, sub in df.groupby(df.index.year):
            if len(sub) < 60:                # skip stub years
                continue
            res = backtest.run(df.loc[sub.index], pos.loc[sub.index], cost_per_side=cost)
            per_year[yr] = res["metrics"]["Total%"]
        rows[f"{inst}/{name}"] = per_year
    tbl = pd.DataFrame(rows).T
    tbl = tbl.reindex(sorted(tbl.columns), axis=1)
    print(tbl.round(1).to_string())
    pos_frac = (tbl > 0).sum(axis=1) / tbl.notna().sum(axis=1)
    print("\nShare of POSITIVE years per sleeve:")
    for k, v in pos_frac.items():
        print(f"  {k:20s} {v*100:4.0f}%  of years green")


# --------------------------------------------------------------------------- #
# 2. Parameter robustness sweeps (OOS Sharpe surfaces)
# --------------------------------------------------------------------------- #
def _grid(inst, fn, param_a, vals_a, param_b, vals_b):
    out = pd.DataFrame(index=vals_a, columns=vals_b, dtype=float)
    df = load(inst)
    for a in vals_a:
        for b in vals_b:
            try:
                pos = fn(df, **{param_a: a, param_b: b})
                out.loc[a, b] = _oos_sharpe(inst, pos)[0]
            except Exception:
                out.loc[a, b] = np.nan
    return out


def robustness():
    print("\n" + "=" * 78)
    print("PARAMETER ROBUSTNESS  ·  out-of-sample Sharpe surfaces (want a PLATEAU)")
    print("=" * 78)

    print("\nGOLD · TrendEMA  (rows=fast EMA, cols=slow EMA, filt=200)")
    print(_grid("GOLD", trend_ema, "fast", [10, 15, 20, 25, 30],
                "slow", [40, 50, 60, 80, 100]).round(2).to_string())

    print("\nSILVER · Bollinger  (rows=window n, cols=band k)")
    print(_grid("SILVER", bollinger_meanrev, "n", [10, 15, 20, 25, 30],
                "k", [1.5, 2.0, 2.5, 3.0]).round(2).to_string())

    print("\nOIL · RSImeanrev  (rows=oversold entry, cols=exit level, period=14)")
    print(_grid("OIL", rsi_meanrev, "lo", [20, 25, 30, 35],
                "hi", [50, 55, 60, 65, 70]).round(2).to_string())

    print("\nBTC · TrendEMA  (rows=fast EMA, cols=slow EMA, filt=200)")
    print(_grid("BTC", trend_ema, "fast", [10, 15, 20, 25, 30],
                "slow", [40, 50, 60, 80, 100]).round(2).to_string())

    print("\nRead: numbers should stay similar across neighbouring cells. A lone")
    print("high cell surrounded by poor ones = curve-fit, do NOT trust it.")


if __name__ == "__main__":
    stability()
    robustness()
