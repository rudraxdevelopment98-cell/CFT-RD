"""Research lab — the honest engine of the whole project.

Runs every strategy on every instrument and, crucially, reports OUT-OF-SAMPLE
results: strategies are judged only on the last ~35% of history they never
"saw", so we don't fool ourselves by curve-fitting the past.

    python -m research.lab                 # all instruments, OOS ranking
    python -m research.lab --full          # also show full-period numbers

Prints, per instrument, each strategy's risk-adjusted metrics vs Buy & Hold,
then a summary of the single best (OOS Sharpe) strategy for each instrument.
"""
from __future__ import annotations

import argparse
import os

import pandas as pd

from . import backtest, metrics
from .strategies import REGISTRY, FAMILY

DATA = os.path.join(os.path.dirname(__file__), "data")
OOS_FRAC = 0.35                       # last 35% of history = unseen test set
CRYPTO = {"BTC", "ETH"}
COLS = ["CAGR%", "Sharpe", "Sortino", "MaxDD%", "Calmar", "Trades",
        "Win%", "PF", "Expect%", "Expo%"]


def load(name):
    df = pd.read_csv(os.path.join(DATA, f"{name}.csv"), index_col=0,
                     parse_dates=True)
    return df[["open", "high", "low", "close", "volume"]].dropna()


def evaluate(df, cost):
    """Return a DataFrame of OOS metrics per strategy, plus Buy&Hold, for df."""
    split = int(len(df) * (1 - OOS_FRAC))
    oos = df.iloc[split:]
    rows = {}
    for name, fn in REGISTRY.items():
        pos = fn(df)                           # signals computed on full history
        res = backtest.run(df.iloc[split:], pos.iloc[split:], cost_per_side=cost)
        rows[name] = res["metrics"]
    rows["Buy&Hold"] = metrics.buy_hold(oos)
    return pd.DataFrame(rows).T[COLS], oos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()

    instruments = [f[:-4] for f in sorted(os.listdir(DATA)) if f.endswith(".csv")]
    best = {}
    for inst in instruments:
        df = load(inst)
        cost = 0.0010 if inst in CRYPTO else 0.0005
        table, oos = evaluate(df, cost)
        print(f"\n{'='*94}\n{inst}  ·  OUT-OF-SAMPLE  {oos.index[0].date()} -> "
              f"{oos.index[-1].date()}  ({len(oos)} bars)  ·  cost {cost*1e4:.0f}bps/side")
        print(table.to_string())

        strat_only = table.drop("Buy&Hold")
        pick = strat_only["Sharpe"].idxmax()
        best[inst] = (pick, FAMILY.get(pick, "-"),
                      strat_only.loc[pick, "Sharpe"],
                      strat_only.loc[pick, "CAGR%"],
                      strat_only.loc[pick, "MaxDD%"],
                      table.loc["Buy&Hold", "Sharpe"])

    print(f"\n{'='*94}\nSUMMARY — best OOS strategy per instrument "
          f"(ranked by Sharpe)\n{'='*94}")
    summ = pd.DataFrame(best, index=["Strategy", "Family", "Sharpe",
                                     "CAGR%", "MaxDD%", "B&H Sharpe"]).T
    summ = summ.sort_values("Sharpe", ascending=False)
    print(summ.to_string())
    print("\nNote: a strategy only earns a place if its OOS Sharpe beats Buy & Hold")
    print("AND its drawdown is tolerable. Win% is deliberately not the ranker.")


if __name__ == "__main__":
    main()
