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
  strategies.py   indicators + 3 strategies (trend / meanrev / breakout)
  risk.py         position sizing, daily loss limit, kill switch (per-day)
  brokers.py      PaperBroker (works) + CcxtBroker + IGBroker (live adapters)
  data.py         unified feed (ccxt + IG) with synthetic offline fallback
  engine.py       one-bar tick: data -> signal -> risk -> execute
  live.py         live orchestration: per-venue runner + scheduling loop
  notify.py       Telegram alerts (console fallback when unconfigured)
  state.py        atomic JSON persistence of kill-switch + stops (restart-safe)
tests/            pytest suite covering strategies, risk, broker, engine, live
```

## Quick start
```bash
pip install -r requirements.txt
python run.py --paper          # offline simulation, no keys needed
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
and persists kill-switch + stop state every cycle so a restart can't silently
re-arm trading mid-drawdown.

Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` to get a push on every
BUY / SELL / halt; without them, alerts just print to the console.

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
```
```
