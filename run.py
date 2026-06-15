"""Run the bot.

    python run.py --paper      # offline simulation on synthetic data (works now)
    python run.py --live       # real loop (needs .env credentials)  [skeleton]

Always prove a strategy in --paper (and the backtester) before --live, and
when you do go live, start on IG's DEMO account and tiny crypto size.
"""
import argparse
import time

from bot.brokers import PaperBroker
from bot.risk import RiskManager
from bot.engine import Engine
from bot import data

# Which markets to trade and with which strategy.
# Crypto symbols are ccxt format; metals are IG epics (placeholders here).
MARKETS = [
    {"name": "BTC",  "symbol": "BTC/USDT",            "strategy": "trend",    "venue": "crypto"},
    {"name": "ETH",  "symbol": "ETH/USDT",            "strategy": "breakout", "venue": "crypto"},
    {"name": "GOLD", "symbol": "CS.D.CFDGOLD.CFDGC.IP","strategy": "trend",   "venue": "metal"},
    {"name": "SILVER","symbol":"CS.D.CFDSILVER.CFDSI.IP","strategy":"meanrev","venue": "metal"},
]


def run_paper():
    broker = PaperBroker(cash=10_000)
    risk = RiskManager(per_trade_pct=0.02, daily_loss_limit_pct=0.05, max_open=3)
    engine = Engine(broker, risk, MARKETS, notify=lambda m: print("  ·", m))

    # build a synthetic price history per market, then replay it bar by bar
    series = {m["name"]: data.synthetic(seed=i, n=500)
              for i, m in enumerate(MARKETS)}
    risk.new_day(broker.cash)

    n = len(next(iter(series.values())))
    print(f"Paper run · {len(MARKETS)} markets · {n} bars\n")
    for bar in range(210, n):                 # warm-up for 200-EMA
        for m in MARKETS:
            window = series[m["name"]].iloc[: bar + 1]
            engine.step(m, window)

    # final mark-to-market
    marks = {m["symbol"]: series[m["name"]].close.iloc[-1] for m in MARKETS}
    eq = broker.equity(marks)
    closed = broker.closed
    wins = [t for t in closed if t > 0]
    print(f"\nFinal equity: {eq:,.0f}  (start 10,000)")
    print(f"Closed trades: {len(closed)} · "
          f"win rate {100*len(wins)/len(closed):.0f}%" if closed else
          "\nNo closed trades this run.")


def run_live():
    raise SystemExit(
        "Live mode is a skeleton. To enable:\n"
        " 1. pip install ccxt requests python-dotenv\n"
        " 2. fill .env (IG demo + read/trade-only crypto keys)\n"
        " 3. swap PaperBroker for CcxtBroker / IGBroker, wire data.fetch_*,\n"
        "    and loop with time.sleep(timeframe) fetching the latest closed bar.\n"
        " 4. run on IG DEMO + tiny crypto size for weeks before real money.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", action="store_true")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    if args.live:
        run_live()
    else:
        run_paper()
