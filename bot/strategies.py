"""Indicators + the three strategies, venue-agnostic.

Each strategy takes an OHLCV DataFrame and returns the *latest* signal:
    'enter', 'exit', or None  (long-only).
The same code is used in backtest and live — that's the point.
"""
import numpy as np
import pandas as pd


# ---- indicators (pure pandas, no TA-Lib) -------------------------------- #
def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


# ---- strategies --------------------------------------------------------- #
# Each returns (signal, stop_pct). signal in {'enter','exit',None}.
def trend(df):
    fast, slow, t = ema(df.close, 20), ema(df.close, 50), ema(df.close, 200)
    up = fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]
    dn = fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]
    if up and df.close.iloc[-1] > t.iloc[-1]:
        return "enter", None
    if dn:
        return "exit", None
    return None, None


def meanrev(df):
    r = rsi(df.close, 14)
    if r.iloc[-1] > 30 and r.iloc[-2] <= 30:
        return "enter", 0.05          # 5% hard stop
    if r.iloc[-1] > 58:
        return "exit", 0.05
    return None, 0.05


def breakout(df):
    hi = df.high.iloc[-21:-1].max()
    lo = df.low.iloc[-11:-1].min()
    vol_ok = df.volume.iloc[-1] > df.volume.iloc[-20:].mean()
    if df.close.iloc[-1] > hi and vol_ok:
        return "enter", None
    if df.close.iloc[-1] < lo:
        return "exit", None
    return None, None


REGISTRY = {"trend": trend, "meanrev": meanrev, "breakout": breakout}
