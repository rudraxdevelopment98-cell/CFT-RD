"""Run the bot.

    python run.py --paper             # offline simulation on synthetic data (works now)
    python run.py --live              # real loop (needs .env credentials)
    python run.py --live --once       # one cycle then exit (cron / smoke test)
    python run.py --live --timeframe 15m

Always prove a strategy in --paper (and the backtester) before --live, and
when you do go live, start on IG's DEMO account and tiny crypto size.
"""
import argparse
import os

from bot.brokers import PaperBroker
from bot.risk import RiskManager
from bot.engine import Engine
from bot import data
from bot.live import Venue, LiveTrader
from bot.notify import Notifier
from bot.state import StateStore

# Which markets to trade and with which strategy.
# Crypto symbols are ccxt format; metals are IG epics (placeholders here).
MARKETS = [
    {"name": "BTC",  "symbol": "BTC/USDT",            "strategy": "trend",    "venue": "crypto"},
    {"name": "ETH",  "symbol": "ETH/USDT",            "strategy": "breakout", "venue": "crypto"},
    {"name": "GOLD", "symbol": "CS.D.CFDGOLD.CFDGC.IP","strategy": "trend",   "venue": "metal"},
    {"name": "SILVER","symbol":"CS.D.CFDSILVER.CFDSI.IP","strategy":"meanrev","venue": "metal"},
]

# Map a candle timeframe to seconds (loop cadence) and to IG's resolution code.
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "4h": 14400, "1d": 86400}
IG_RESOLUTION = {"1m": "MINUTE", "5m": "MINUTE_5", "15m": "MINUTE_15",
                 "30m": "MINUTE_30", "1h": "HOUR", "4h": "HOUR_4", "1d": "DAY"}


def run_paper():
    broker = PaperBroker(cash=10_000)
    risk = RiskManager(per_trade_pct=0.02, daily_loss_limit_pct=0.05, max_open=3)
    notify = Notifier.from_env()
    engine = Engine(broker, risk, MARKETS, notify=notify)

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


def build_live_venues(timeframe, notify):
    """Construct the crypto and metals venues from .env credentials.

    Each venue is independent: its own broker, risk manager, data fetcher and
    state file. A venue is only built if its credentials are present, so you can
    run crypto-only or metals-only.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # env may be exported directly; dotenv is just a convenience

    crypto_markets = [m for m in MARKETS if m["venue"] == "crypto"]
    metal_markets = [m for m in MARKETS if m["venue"] == "metal"]
    venues = []

    if crypto_markets and os.getenv("CRYPTO_API_KEY"):
        from bot.brokers import CcxtBroker
        exchange = os.getenv("CRYPTO_EXCHANGE", "binance")
        broker = CcxtBroker(
            exchange, os.environ["CRYPTO_API_KEY"], os.environ["CRYPTO_SECRET"])
        venues.append(Venue(
            "crypto", broker,
            RiskManager(per_trade_pct=0.02, daily_loss_limit_pct=0.05, max_open=2),
            crypto_markets,
            fetch=lambda m: data.fetch_crypto(m["symbol"], timeframe, exchange=exchange),
            notify=notify, state=StateStore("state_crypto.json")))

    if metal_markets and os.getenv("IG_API_KEY"):
        from bot.brokers import IGBroker
        ig = IGBroker(
            os.environ["IG_API_KEY"], os.environ["IG_IDENTIFIER"],
            os.environ["IG_PASSWORD"],
            demo=os.getenv("IG_DEMO", "true").lower() != "false")
        resolution = IG_RESOLUTION.get(timeframe, "HOUR")
        venues.append(Venue(
            "metals", ig,
            RiskManager(per_trade_pct=0.02, daily_loss_limit_pct=0.05, max_open=2),
            metal_markets,
            fetch=lambda m: data.fetch_metal_ig(ig, m["symbol"], resolution),
            notify=notify, state=StateStore("state_metals.json")))

    return venues


def run_live(timeframe="1h", once=False):
    notify = Notifier.from_env()
    venues = build_live_venues(timeframe, notify)
    if not venues:
        raise SystemExit(
            "No live venues configured. Copy .env.example -> .env and fill in\n"
            "IG demo creds and/or read+trade-only crypto keys, then:\n"
            "  pip install ccxt requests python-dotenv\n"
            "Start on IG DEMO + tiny crypto size for weeks before real money.")

    period = TF_SECONDS.get(timeframe, 3600)
    LiveTrader(venues, period_s=period, notify=notify).run(
        max_cycles=1 if once else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--timeframe", default="1h",
                    help="candle size / loop cadence, e.g. 15m, 1h, 4h, 1d")
    ap.add_argument("--once", action="store_true",
                    help="run a single live cycle then exit")
    args = ap.parse_args()
    if args.live:
        run_live(timeframe=args.timeframe, once=args.once)
    else:
        run_paper()
