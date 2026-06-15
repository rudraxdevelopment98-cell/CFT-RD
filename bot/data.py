"""Unified OHLCV feed.

    crypto  -> ccxt (real exchange candles)
    metals  -> IG prices REST endpoint
    offline -> synthetic generator, so paper mode runs with no network/keys
"""
import numpy as np
import pandas as pd


def synthetic(n=600, seed=0):
    rng = np.random.default_rng(seed)
    rets, segs = [], []
    while sum(len(s) for s in segs) < n:
        drift = rng.choice([0.0008, -0.0006, 0.0])
        segs.append(rng.normal(drift, rng.choice([0.01, 0.02]), rng.integers(80, 200)))
    rets = np.concatenate(segs)[:n]
    close = 1000 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    op = np.concatenate([[close[0]], close[:-1]])
    vol = rng.uniform(50, 200, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": op, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


def fetch_crypto(symbol, timeframe="1h", limit=300, exchange="binance"):
    import ccxt
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    o = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("ts")


def fetch_metal_ig(broker, epic, resolution="HOUR", limit=300):
    """Pull candles from IG's /prices endpoint (needs a live IGBroker session)."""
    r = broker.s.get(f"{broker.base}/prices/{epic}",
                     params={"resolution": resolution, "max": limit},
                     headers={"Version": "3"})
    rows = r.json()["prices"]
    def mid(p):  # IG gives bid/ask; use mid
        return [(b["bid"] + b["ask"]) / 2 for b in [p]][0]
    df = pd.DataFrame([{
        "ts": p["snapshotTimeUTC"],
        "open": (p["openPrice"]["bid"] + p["openPrice"]["ask"]) / 2,
        "high": (p["highPrice"]["bid"] + p["highPrice"]["ask"]) / 2,
        "low": (p["lowPrice"]["bid"] + p["lowPrice"]["ask"]) / 2,
        "close": (p["closePrice"]["bid"] + p["closePrice"]["ask"]) / 2,
        "volume": p.get("lastTradedVolume", 0)} for p in rows])
    df["ts"] = pd.to_datetime(df["ts"])
    return df.set_index("ts")
