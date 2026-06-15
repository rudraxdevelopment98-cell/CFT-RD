"""Shared test helpers."""
import numpy as np
import pandas as pd


def ohlcv(closes, highs=None, lows=None, volume=None):
    """Build an OHLCV DataFrame from a list of closes (with sane defaults)."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    highs = np.asarray(highs, float) if highs is not None else closes * 1.001
    lows = np.asarray(lows, float) if lows is not None else closes * 0.999
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volume = np.asarray(volume, float) if volume is not None else np.full(n, 100.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": volume}, index=idx)


class FakeBroker:
    """Minimal in-memory broker for engine/live tests (mirrors PaperBroker's
    surface without fees/slippage so expected values are exact)."""

    def __init__(self, cash=10_000):
        self.cash = cash
        self.positions = {}
        self.orders = []

    def equity(self, marks):
        val = self.cash
        for sym, p in self.positions.items():
            val += p["units"] * marks.get(sym, p["entry"])
        return val

    def position(self, symbol):
        return self.positions.get(symbol)

    def open_count(self):
        return len(self.positions)

    def buy(self, symbol, stake, price, stop=None):
        units = stake / price
        self.cash -= stake
        self.positions[symbol] = {"units": units, "entry": price,
                                  "cost": stake, "stop": stop}
        self.orders.append(("buy", symbol, price))
        return {"symbol": symbol}

    def close(self, symbol, price):
        p = self.positions.pop(symbol, None)
        if not p:
            return None
        proceeds = p["units"] * price
        self.cash += proceeds
        self.orders.append(("sell", symbol, price))
        return {"symbol": symbol, "pnl_pct": proceeds / p["cost"] - 1}
