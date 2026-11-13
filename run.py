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
from bot.database import Database
from bot.retry import ResilientBroker
from bot.logconf import setup_logging

# Where state snapshots + logs live. Point it at a mounted volume in Docker so
# they survive a container/host restart.
DATA_DIR = os.getenv("TRADER_DATA_DIR", ".")

# Which markets to trade and with which strategy.
# Strategy per market is the OUT-OF-SAMPLE winner from research/ (see RESEARCH.md):
#   Gold/BTC/ETH -> trend, Silver -> bollinger, Oil -> meanrev (RSI).
# FX majors were dropped (no reliable edge). Crypto symbols are ccxt format;
# commodities are IG epics (placeholders — CONFIRM current epics in IG's API
# companion before trading, they differ between demo/live and change over time).
MARKETS = [
    {"name": "BTC",   "symbol": "BTC/GBP",                "strategy": "trend",     "venue": "crypto"},
    {"name": "ETH",   "symbol": "ETH/GBP",                "strategy": "trend",     "venue": "crypto"},
    {"name": "GOLD",  "symbol": "CS.D.CFDGOLD.CFDGC.IP",  "strategy": "trend",     "venue": "ig"},
    {"name": "SILVER","symbol": "CS.D.CFDSILVER.CFDSI.IP","strategy": "bollinger", "venue": "ig"},
    # Oil edge is real but FRAGILE (−37% in 2020). Keep smallest size; meanrev
    # carries a hard stop. Confirm the oil epic before enabling.
    {"name": "OIL",   "symbol": "CC.D.CL.USS.IP",         "strategy": "meanrev",   "venue": "ig"},
]

# Map a candle timeframe to seconds (loop cadence) and to IG's resolution code.
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "4h": 14400, "1d": 86400}
IG_RESOLUTION = {"1m": "MINUTE", "5m": "MINUTE_5", "15m": "MINUTE_15",
                 "30m": "MINUTE_30", "1h": "HOUR", "4h": "HOUR_4", "1d": "DAY"}


def run_paper():
    broker = PaperBroker(cash=10_000)
    risk = sized_risk(len(MARKETS), daily_loss_limit_pct=0.05)
    notify = Notifier.from_env()
    engine = Engine(broker, risk, MARKETS, notify=notify)

    # build a synthetic price history per market, then replay it bar by bar
    series = {m["name"]: data.synthetic(seed=i, n=500)
              for i, m in enumerate(MARKETS)}
    risk.new_day(broker.cash)

    n = len(next(iter(series.values())))
    print(f"Paper run · {len(MARKETS)} markets · {n} bars\n")
    for bar in range(210, n):                 # warm-up for 200-EMA
        # account-wide marks for this bar, so the kill switch values every
        # open position (not just the one being stepped).
        marks = {m["symbol"]: series[m["name"]].close.iloc[bar] for m in MARKETS}
        for m in MARKETS:
            window = series[m["name"]].iloc[: bar + 1]
            engine.step(m, window, marks=marks)

    # final mark-to-market
    marks = {m["symbol"]: series[m["name"]].close.iloc[-1] for m in MARKETS}
    eq = broker.equity(marks)
    closed = broker.closed
    wins = [t for t in closed if t > 0]
    print(f"\nFinal equity: {eq:,.0f}  (start 10,000)")
    print(f"Closed trades: {len(closed)} · "
          f"win rate {100*len(wins)/len(closed):.0f}%" if closed else
          "\nNo closed trades this run.")


def sized_risk(n_markets, daily_loss_limit_pct):
    """Size like the research portfolio: each market gets an equal 1/N share of
    its venue's equity, and every market may be open at once. (The old 2%-per-
    trade setting ran ~1/10 of the validated exposure.)"""
    return RiskManager(per_trade_pct=1.0 / n_markets,
                       daily_loss_limit_pct=daily_loss_limit_pct, max_open=n_markets)


def open_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    return Database(os.path.join(DATA_DIR, "trading.db"))


def build_live_venues(timeframe, notify, db=None):
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
    ig_markets = [m for m in MARKETS if m["venue"] == "ig"]
    venues = []

    if crypto_markets and os.getenv("CRYPTO_API_KEY"):
        from bot.brokers import CcxtBroker
        exchange = os.getenv("CRYPTO_EXCHANGE", "kraken")
        broker = ResilientBroker(CcxtBroker(
            exchange, os.environ["CRYPTO_API_KEY"], os.environ["CRYPTO_SECRET"],
            quote=os.getenv("CRYPTO_QUOTE", "GBP")), notify=notify)
        venues.append(Venue(
            "crypto", broker,
            # 8%: at research sizing the crypto book had 16 days below -5% in
            # 3.5 years (a 5% limit would sell dips) but only 2 below -8%.
            sized_risk(len(crypto_markets), daily_loss_limit_pct=0.08),
            crypto_markets,
            fetch=lambda m: data.fetch_crypto(m["symbol"], timeframe, exchange=exchange),
            notify=notify, db=db))

    if ig_markets and os.getenv("IG_API_KEY"):
        from bot.brokers import IGBroker
        ig = IGBroker(
            os.environ["IG_API_KEY"], os.environ["IG_IDENTIFIER"],
            os.environ["IG_PASSWORD"],
            demo=os.getenv("IG_DEMO", "true").lower() != "false")
        resolution = IG_RESOLUTION.get(timeframe, "HOUR")
        venues.append(Venue(
            "ig", ResilientBroker(ig, notify=notify),
            sized_risk(len(ig_markets), daily_loss_limit_pct=0.05),
            ig_markets,
            fetch=lambda m: data.fetch_metal_ig(ig, m["symbol"], resolution),
            notify=notify, db=db))

    return venues


def run_live(timeframe="1d", once=False):
    log = setup_logging(DATA_DIR)
    notify = Notifier.from_env(echo=log.info)         # log every BUY/SELL/halt
    log.info("Starting live trader (timeframe=%s)", timeframe)
    db = open_db()
    venues = build_live_venues(timeframe, notify, db=db)
    if not venues:
        raise SystemExit(
            "No live venues configured. Copy .env.example -> .env and fill in\n"
            "IG demo creds and/or read+trade-only crypto keys, then:\n"
            "  pip install ccxt requests python-dotenv\n"
            "Start on IG DEMO + tiny crypto size for weeks before real money.")

    period = TF_SECONDS.get(timeframe, 3600)
    LiveTrader(venues, period_s=period, notify=notify, db=db, mode="live").run(
        max_cycles=1 if once else None)


# Markets for paper-live: same validated strategies, fetched from Yahoo (daily,
# no keys). Symbols double as the instrument name so paper P&L reads cleanly.
PAPERLIVE_MARKETS = [
    {"name": "GOLD",  "symbol": "GOLD",  "ticker": "GC=F",    "strategy": "trend"},
    {"name": "SILVER","symbol": "SILVER","ticker": "SI=F",    "strategy": "bollinger"},
    {"name": "OIL",   "symbol": "OIL",   "ticker": "CL=F",    "strategy": "meanrev"},
    {"name": "BTC",   "symbol": "BTC",   "ticker": "BTC-USD", "strategy": "trend"},
    {"name": "ETH",   "symbol": "ETH",   "ticker": "ETH-USD", "strategy": "trend"},
]


def run_paperlive(once=False):
    """Trade REAL daily market data with fake money — no account, no keys, no
    risk. The best first step: watch the bot analyse live markets."""
    log = setup_logging(DATA_DIR)
    notify = Notifier.from_env(echo=log.info)
    db = open_db()
    broker = PaperBroker(cash=10_000)
    risk = sized_risk(len(PAPERLIVE_MARKETS), daily_loss_limit_pct=0.05)
    venue = Venue(
        "paperlive", broker, risk, PAPERLIVE_MARKETS,
        fetch=lambda m: data.fetch_yahoo(m["ticker"]),
        notify=notify, db=db, report_equity=True)
    log.info("Paper-LIVE on real market data · fake £10,000 · daily check · "
             "%d markets", len(PAPERLIVE_MARKETS))
    # one check per day; the process stays up and re-checks every 24h.
    LiveTrader([venue], period_s=86_400, notify=notify, db=db,
               mode="paperlive").run(
        max_cycles=1 if once else None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", action="store_true",
                    help="offline simulation on synthetic data")
    ap.add_argument("--paperlive", action="store_true",
                    help="REAL market data, fake money, no keys (recommended first)")
    ap.add_argument("--live", action="store_true",
                    help="real orders (needs .env credentials)")
    ap.add_argument("--timeframe", default="1d",
                    help="candle size / loop cadence. Strategies were validated on "
                         "1d only; other values are untested")
    ap.add_argument("--once", action="store_true",
                    help="run a single cycle then exit")
    args = ap.parse_args()
    if args.live:
        run_live(timeframe=args.timeframe, once=args.once)
    elif args.paperlive:
        run_paperlive(once=args.once)
    else:
        run_paper()
