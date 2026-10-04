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
def trend_ema(df):
    """EMA 20/50 above + price above 200-EMA regime filter."""
    c = df.close
    cond = (ema(c, 20) > ema(c, 50)) & (c > ema(c, 200))
    return cond.astype(float)


def ts_momentum(df):
    """Time-series momentum: long while above the 200-day SMA. The single most
    robust published trend rule across assets."""
    return (df.close > sma(df.close, 200)).astype(float)


def dual_sma(df):
    """Classic 50/200 golden-cross regime."""
    return (sma(df.close, 50) > sma(df.close, 200)).astype(float)


def macd_trend(df):
    """MACD(12,26,9) line above its signal -> long."""
    macd = ema(df.close, 12) - ema(df.close, 26)
    signal = ema(macd, 9)
    return (macd > signal).astype(float)


# --- event / stateful strategies ------------------------------------------ #
def donchian_breakout(df):
    """Enter on a new 20-day high, exit on a 10-day low (trailing channel)."""
    hi = df.high.rolling(20).max().shift()
    lo = df.low.rolling(10).min().shift()
    entries = (df.close > hi).fillna(False)
    exits = (df.close < lo).fillna(False)
    return _position_from_signals(entries, exits)


def rsi_meanrev(df):
    """Buy the bounce: RSI(14) crossing back up through 30; exit when RSI>58."""
    r = rsi(df.close, 14)
    entries = ((r > 30) & (r.shift() <= 30)).fillna(False)
    exits = (r > 58).fillna(False)
    return _position_from_signals(entries, exits)


def bollinger_meanrev(df):
    """Buy a close below the lower Bollinger band (20,2); exit at the mid band."""
    mid = sma(df.close, 20)
    sd = df.close.rolling(20).std()
    entries = (df.close < mid - 2 * sd).fillna(False)
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
