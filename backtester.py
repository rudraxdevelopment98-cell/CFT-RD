"""
Crypto Strategy Backtester
==========================
Tests three complementary trading strategies on historical OHLCV data:

    1. Trend-following  -> EMA crossover (20/50) with a 200-EMA regime filter
    2. Mean reversion   -> RSI(14) oversold bounce, with a hard stop-loss
    3. Breakout         -> Donchian channel (20 high in / 10 low out) + volume filter

It reports, per strategy: total return, max drawdown, win rate, avg win/loss,
profit factor and number of trades -- and compares everything against simply
buying and holding the asset (the benchmark that actually matters).

Fees and slippage are applied on every fill so the numbers are not fantasy.

USAGE
-----
    pip install pandas numpy ccxt matplotlib

    # Live data (recommended): pulls real candles from an exchange
    python backtester.py --symbol BTC/USDT --timeframe 1h --candles 3000

    # No network / offline: runs on synthetic data so you can see it work
    python backtester.py --synthetic

Long-only by design (matches the strategy descriptions). Treat this as a
research tool, not financial advice -- a winning backtest means "worth a tiny
demo test", never "this prints money".
"""

import argparse
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# 1. DATA
# --------------------------------------------------------------------------- #
def load_live(symbol="BTC/USDT", timeframe="1h", candles=3000, exchange="binance"):
    """Fetch real OHLCV via ccxt, paginating backwards to collect `candles` bars."""
    import ccxt

    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    since = ex.milliseconds() - candles * tf_ms
    rows = []
    while len(rows) < candles:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + tf_ms
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("ts")


def make_synthetic(n=3000, seed=42):
    """Geometric-brownian-ish price path with regime shifts, so all three
    strategies get something to chew on when there's no network access."""
    rng = np.random.default_rng(seed)
    # stitch together trending and choppy regimes
    rets = []
    while len(rets) < n:
        drift = rng.choice([0.0008, -0.0006, 0.0])   # up trend / down trend / chop
        vol = rng.choice([0.01, 0.02, 0.015])
        length = rng.integers(150, 400)
        rets.append(rng.normal(drift, vol, length))
    rets = np.concatenate(rets)[:n]
    close = 30000 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    vol = rng.uniform(50, 200, n) * (1 + np.abs(rets) * 20)
    idx = pd.date_range("2022-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# --------------------------------------------------------------------------- #
# 2. INDICATORS  (pure pandas/numpy -- no TA-Lib install pain)
# --------------------------------------------------------------------------- #
def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def rsi(s, period=14):
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


# --------------------------------------------------------------------------- #
# 3. STRATEGIES  -> each returns (entries, exits) boolean Series + optional stop
# --------------------------------------------------------------------------- #
def strat_trend(df):
    fast, slow, trend = ema(df.close, 20), ema(df.close, 50), ema(df.close, 200)
    cross_up = (fast > slow) & (fast.shift() <= slow.shift())
    cross_dn = (fast < slow) & (fast.shift() >= slow.shift())
    entries = cross_up & (df.close > trend)        # only long with the big trend
    exits = cross_dn
    return entries.fillna(False), exits.fillna(False), None


def strat_meanrev(df):
    r = rsi(df.close, 14)
    entries = (r > 30) & (r.shift() <= 30)         # cross back up out of oversold
    exits = r > 58                                 # take profit on reversion
    return entries.fillna(False), exits.fillna(False), 0.05  # 5% hard stop


def strat_breakout(df):
    hi20 = df.high.rolling(20).max().shift()       # shift -> use *prior* range
    lo10 = df.low.rolling(10).min().shift()
    vol_ok = df.volume > df.volume.rolling(20).mean()
    entries = (df.close > hi20) & vol_ok
    exits = df.close < lo10                         # trailing channel exit
    return entries.fillna(False), exits.fillna(False), None


STRATEGIES = {
    "Trend (EMA cross)": strat_trend,
    "MeanRev (RSI)": strat_meanrev,
    "Breakout (Donchian)": strat_breakout,
}


# --------------------------------------------------------------------------- #
# 4. BACKTEST ENGINE  (event-driven, long/flat, fees + slippage on every fill)
# --------------------------------------------------------------------------- #
def backtest(df, entries, exits, stop_pct=None, capital=10_000, fee=0.001, slip=0.0005):
    cash = capital
    units = 0.0
    in_pos = False
    entry_eq = 0.0
    equity_curve = []
    trades = []

    closes = df.close.values
    ent = entries.values
    ex = exits.values

    for i in range(len(df)):
        px = closes[i]

        if in_pos:
            stop_hit = stop_pct is not None and px <= entry_eq_price * (1 - stop_pct)
            if ex[i] or stop_hit:
                fill = px * (1 - slip)
                cash = units * fill * (1 - fee)
                trades.append(cash / entry_eq - 1.0)   # trade return %
                units, in_pos = 0.0, False
        else:
            if ent[i]:
                fill = px * (1 + slip)
                units = (cash * (1 - fee)) / fill
                entry_eq = cash
                entry_eq_price = fill
                cash = 0.0
                in_pos = True

        equity_curve.append(cash if not in_pos else units * px)

    return pd.Series(equity_curve, index=df.index), trades


# --------------------------------------------------------------------------- #
# 5. METRICS
# --------------------------------------------------------------------------- #
def metrics(equity, trades, capital):
    total_ret = equity.iloc[-1] / capital - 1
    dd = (equity / equity.cummax() - 1).min()
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")
    return {
        "Return %": round(total_ret * 100, 1),
        "MaxDD %": round(dd * 100, 1),
        "Trades": len(trades),
        "Win %": round(win_rate * 100, 1),
        "AvgWin %": round(avg_win * 100, 2),
        "AvgLoss %": round(avg_loss * 100, 2),
        "ProfitFactor": round(pf, 2) if pf != float("inf") else "inf",
    }


# --------------------------------------------------------------------------- #
# 6. RUN
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="1h")
    p.add_argument("--candles", type=int, default=3000)
    p.add_argument("--exchange", default="binance")
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--synthetic", action="store_true", help="run on fake data offline")
    p.add_argument("--plot", action="store_true", help="save equity_curves.png")
    args = p.parse_args()

    if args.synthetic:
        df = make_synthetic(args.candles)
        label = "SYNTHETIC DATA"
    else:
        try:
            df = load_live(args.symbol, args.timeframe, args.candles, args.exchange)
            label = f"{args.symbol} {args.timeframe} ({len(df)} candles)"
        except Exception as e:
            print(f"[!] Live fetch failed ({e}); falling back to synthetic data.\n")
            df = make_synthetic(args.candles)
            label = "SYNTHETIC DATA (fallback)"

    # benchmark: buy & hold
    bh_return = df.close.iloc[-1] / df.close.iloc[0] - 1
    bh_dd = (df.close / df.close.cummax() - 1).min()

    print(f"\n=== Backtest: {label} ===")
    print(f"Period: {df.index[0].date()} -> {df.index[-1].date()}\n")

    results = {}
    curves = {}
    for name, fn in STRATEGIES.items():
        entries, exits, stop = fn(df)
        equity, trades = backtest(df, entries, exits, stop_pct=stop, capital=args.capital)
        results[name] = metrics(equity, trades, args.capital)
        curves[name] = equity

    table = pd.DataFrame(results).T
    print(table.to_string())
    print(
        f"\nBenchmark  Buy & Hold:  Return {bh_return*100:6.1f}%   "
        f"MaxDD {bh_dd*100:6.1f}%"
    )
    print("\nRead it like this: a strategy is only interesting if it beats Buy & Hold")
    print("on a RISK-ADJUSTED basis -- i.e. similar/better return at a smaller MaxDD.\n")

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.figure(figsize=(11, 6))
        for name, eq in curves.items():
            plt.plot(eq.index, eq.values, label=name, linewidth=1.3)
        bh = args.capital * (df.close / df.close.iloc[0])
        plt.plot(bh.index, bh.values, "--", color="grey", label="Buy & Hold")
        plt.title(f"Equity curves — {label}")
        plt.ylabel("Account equity"); plt.legend(); plt.tight_layout()
        plt.savefig("equity_curves.png", dpi=120)
        print("Saved equity_curves.png\n")


if __name__ == "__main__":
    main()
