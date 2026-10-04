"""Strategy library for research — each returns a target LONG/FLAT position
series (1.0 = fully long, 0.0 = flat) aligned to the decision bar. The
backtester shifts by one bar so signals are acted on the *next* open, never
the same bar they are computed on (no look-ahead).

Long/flat only, to match the spread-bet / spot reality of the live bot and to
keep the comparison honest. Each is a classic, widely-documented strategy — we
are testing which *regime* each instrument rewards, not inventing magic.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def sma(s, n):
    return s.rolling(n).mean()


def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def atr(df, period=14):
    tr = pd.concat([
        df.high - df.low,
        (df.high - df.close.shift()).abs(),
        (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _position_from_signals(entries: pd.Series, exits: pd.Series) -> pd.Series:
    """Turn entry/exit booleans into a held 0/1 position (enter on entry,
    stay until exit). Stateful forward-fill."""
    pos = np.zeros(len(entries))
    held = 0
    e, x = entries.values, exits.values
    for i in range(len(pos)):
        if held and x[i]:
            held = 0
        elif not held and e[i]:
            held = 1
        pos[i] = held
    return pd.Series(pos, index=entries.index)


# --- regime / trend strategies (position = condition) --------------------- #
# Params carry defaults, so `fn(df)` still works everywhere; the walk-forward
# robustness sweep passes other values to check the edge isn't a lone spike.
def trend_ema(df, fast=20, slow=50, filt=200):
    """EMA fast/slow above + price above a longer-EMA regime filter."""
    c = df.close
    cond = (ema(c, fast) > ema(c, slow)) & (c > ema(c, filt))
    return cond.astype(float)


def ts_momentum(df, n=200):
    """Time-series momentum: long while above the n-day SMA. The single most
    robust published trend rule across assets."""
    return (df.close > sma(df.close, n)).astype(float)


def dual_sma(df, fast=50, slow=200):
    """Classic golden-cross regime (fast SMA above slow SMA)."""
    return (sma(df.close, fast) > sma(df.close, slow)).astype(float)


def macd_trend(df, fast=12, slow=26, sig=9):
    """MACD line above its signal -> long."""
    macd = ema(df.close, fast) - ema(df.close, slow)
    signal = ema(macd, sig)
    return (macd > signal).astype(float)


# --- event / stateful strategies ------------------------------------------ #
def donchian_breakout(df, entry=20, exit=10):
    """Enter on a new `entry`-day high, exit on an `exit`-day low (channel)."""
    hi = df.high.rolling(entry).max().shift()
    lo = df.low.rolling(exit).min().shift()
    entries = (df.close > hi).fillna(False)
    exits = (df.close < lo).fillna(False)
    return _position_from_signals(entries, exits)


def rsi_meanrev(df, period=14, lo=30, hi=58):
    """Buy the bounce: RSI crossing back up through `lo`; exit when RSI>`hi`."""
    r = rsi(df.close, period)
    entries = ((r > lo) & (r.shift() <= lo)).fillna(False)
    exits = (r > hi).fillna(False)
    return _position_from_signals(entries, exits)


def bollinger_meanrev(df, n=20, k=2.0):
    """Buy a close below the lower Bollinger band (n,k); exit at the mid band."""
    mid = sma(df.close, n)
    sd = df.close.rolling(n).std()
    entries = (df.close < mid - k * sd).fillna(False)
    exits = (df.close >= mid).fillna(False)
    return _position_from_signals(entries, exits)


REGISTRY = {
    "TrendEMA": trend_ema,
    "TSmom200": ts_momentum,
    "DualSMA": dual_sma,
    "MACD": macd_trend,
    "Donchian": donchian_breakout,
    "RSImeanrev": rsi_meanrev,
    "Bollinger": bollinger_meanrev,
}

# Which strategies are trend-following vs mean-reverting (for interpretation).
FAMILY = {
    "TrendEMA": "trend", "TSmom200": "trend", "DualSMA": "trend",
    "MACD": "trend", "Donchian": "trend",
    "RSImeanrev": "meanrev", "Bollinger": "meanrev",
}
