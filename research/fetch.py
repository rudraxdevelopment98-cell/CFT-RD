"""Download & cache daily OHLCV for the research universe (Yahoo Finance).

    python -m research.fetch              # 10y daily for all instruments

Data is cached to research/data/*.csv (git-ignored; regenerate any time).
Yahoo is fine for research; live trading uses ccxt (crypto) / IG (metals).
"""
import os
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

TICKERS = {
    "GOLD": "GC=F", "SILVER": "SI=F", "OIL": "CL=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X",
    "BTC": "BTC-USD", "ETH": "ETH-USD",
}
DATA = os.path.join(os.path.dirname(__file__), "data")


def main(period="10y"):
    import yfinance as yf
    os.makedirs(DATA, exist_ok=True)
    for name, tk in TICKERS.items():
        d = yf.download(tk, period=period, interval="1d",
                        progress=False, auto_adjust=True)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
        d.columns = ["open", "high", "low", "close", "volume"]
        d.to_csv(os.path.join(DATA, f"{name}.csv"))
        print(f"{name:8s} {len(d):5d} bars  {d.index[0].date()} -> {d.index[-1].date()}")


if __name__ == "__main__":
    main()
