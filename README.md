# Personal Trader

A private, single-user trading bot for **gold, silver, and crypto**.
Crypto runs on a normal exchange via `ccxt`; gold & silver run on **IG spread
betting** (tax-free gains in the UK, real XAU/XAG markets, demo account for
paper trading).

> Personal use only — your own money, your own accounts. Not a product for
> others, not financial advice. Capital at risk; leverage on the metals side
> cuts both ways.

## Structure
```
run.py            entry point (--paper offline; --live runs the real loop)
bot/
  strategies.py   indicators + strategies (trend / meanrev / breakout / bollinger)
  risk.py         position sizing, daily loss limit, kill switch (per-day)
  brokers.py      PaperBroker (works) + CcxtBroker + IGBroker (live adapters)
  data.py         unified feed (ccxt + IG) with synthetic offline fallback
  engine.py       one-bar tick: data -> signal -> risk -> execute
  live.py         live orchestration: per-venue runner + scheduling loop
  notify.py       Telegram alerts (console fallback when unconfigured)
  database.py     SQLite source of truth: trades, positions, heartbeats, equity
  retry.py        exponential backoff for network reads (orders never retried)
  state.py        JSON state store (used only when no database is configured)
portal/           read-only FastAPI monitoring portal (python -m portal)
tests/            pytest suite: strategies, risk, broker, engine, live, DB, portal
```

## Quick start
```bash
pip install -r requirements.txt
python run.py --paperlive      # REAL market data, fake money, no keys (start here — see START_HERE.md)
python run.py --paper          # offline simulation on synthetic data
pytest -q                      # run the test suite
```

## Live mode
```bash
cp .env.example .env           # fill in IG demo creds and/or crypto keys
python run.py --live --once             # one cycle then exit (cron / smoke test)
python run.py --live --timeframe 1h     # continuous loop on 1h candles
```
Crypto and metals are independent venues — each has its own broker, risk
manager and state file, and a venue is only started if its credentials are
present (so you can run crypto-only or metals-only). The loop trades the last
**closed** bar, re-arms the daily kill switch at each calendar-day rollover,
and records every open/close in `trading.db` (SQLite) in one transaction. After
a crash or restart it reloads open positions, stops, paper cash and today's
kill-switch state from the database, so it never starts from a blank slate.
Network reads (prices, balances) retry with exponential backoff; orders are
never retried, because a timed-out order may still have been filled.

Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` to get a push on every
BUY / SELL / halt; without them, alerts just print to the console.

### Which market trades which strategy
Each market in `run.py`'s `MARKETS` is mapped to the strategy that won **out of
sample** in `research/` (see `RESEARCH.md`):

| Market | Strategy | Why |
|---|---|---|
| Gold, BTC, ETH | `trend` | trend-following; robust params, mostly-green years |
| Silver | `bollinger` | mean-reversion off the 2σ lower band |
| Oil | `meanrev` | RSI bounce — **fragile**, smallest size, hard stop |

FX majors were tested and **dropped** — no reliable edge. Re-run the research
monthly (`python -m research.lab`) and retire any sleeve that stops working.

## Portal (read-only monitoring)
```bash
PORTAL_PASSWORD=choose-one python -m portal     # http://127.0.0.1:8080
```
Shows bot health (online / waiting / offline), run mode, today's P&L, total
equity, win rate, max drawdown, the equity curve, every market with its
strategy and live P&L, and recent trades. Refreshes every 10 s.

It **cannot change anything**: only GET routes exist and it opens
`trading.db` in SQLite read-only mode. Every page needs the username/password
(`PORTAL_USER`, default `admin`, and `PORTAL_PASSWORD`).

Basic auth sends the password with each request, so the portal listens on
127.0.0.1 only. From your laptop, open an SSH tunnel to the VPS and browse
locally:
```bash
ssh -L 8080:127.0.0.1:8080 you@your-vps     # then open http://localhost:8080
```

## Deploy (run it 24/7)
`trading.db` and a rotating `trader.log` are written to `$TRADER_DATA_DIR`
(default `.`); point it at a persistent volume.

**Docker (recommended):**
```bash
cp .env.example .env     # fill in creds + PORTAL_PASSWORD; IG_DEMO stays true
docker compose up -d     # bot (--paperlive by default) + portal on 127.0.0.1:8080
docker compose logs -f trader
```
Data persists in `./var`. Switch the trader's `command` to `--live` in
`docker-compose.yml` only after the demo phase.

**systemd (VPS / Raspberry Pi, no Docker):** see
`deploy/personal-trader.service` — it has the full setup steps in its header,
then `journalctl -u personal-trader -f` to follow logs.

Both default to **IG demo** (`IG_DEMO=true`). Prove weeks of good behaviour on
demo before switching to a live account.

## Path to live (do not skip steps)
1. **Backtest** each strategy/market with the separate `backtester.py` across
   bull / bear / chop periods. Keep only what survives on a risk-adjusted basis.
2. **Paper** here with `--paper` to confirm the plumbing.
3. **Demo live**: copy `.env.example` -> `.env`, add IG **demo** creds +
   read/trade-only crypto keys (withdrawals disabled, IP-whitelisted), wire the
   live brokers in `run_live()`, and run for *weeks*.
4. **Tiny real**: smallest possible size. Scale only after it behaves.

## Safety
- Crypto API keys: trade-only, **withdrawal disabled**, IP-whitelisted.
- Secrets in `.env` (git-ignored) or a secrets manager — never in code.
- `RiskManager` daily loss limit is a hard kill switch; keep it on.
- IG epics differ between demo/live and change over time — confirm in IG's API
  companion before trading.
