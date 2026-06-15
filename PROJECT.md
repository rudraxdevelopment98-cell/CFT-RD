# PROJECT — Personal Multi-Asset Trading Bot

> Handoff doc. Read this first in the Claude Code session — it captures the
> goal, decisions, architecture, and the build roadmap so you don't have to
> re-explain anything.

## Goal
A **private, single-user** bot that trades **gold, silver, and crypto** to
grow my own capital. Not a product for others, not a service — just my own
accounts, my own money, fully automated.

Because it's personal-use only, the heavy UK regulatory stuff (FCA financial
promotion rules, authorisation for handling other people's money) does **not**
apply — that's all about offering services/promoting to the public. Remaining
real constraints: my capital is at risk, metals are leveraged, and gains are
taxable (spread-betting gains are currently CGT-free in the UK; crypto is not —
confirm with an accountant).

## Key decision — how each asset is accessed
| Asset         | Venue                     | Why                                            |
|---------------|---------------------------|------------------------------------------------|
| Crypto        | Exchange via `ccxt`       | Mature APIs, 24/7, unified across 100 exchanges |
| Gold / Silver | **IG spread betting**     | Tax-free UK gains, real XAU/XAG markets, demo account, good REST+streaming API |

Rejected alternatives: tokenized metals (taxable, thin silver liquidity),
OANDA CFDs (taxable), Interactive Brokers (overkill/complex to start).

It's a **hybrid** build: crypto = `ccxt`, metals = IG REST. One execution
adapter per venue, behind a common `Broker` interface.

## The three strategies (complementary by market regime)
1. **Trend** — EMA 20/50 crossover, 200-EMA regime filter. Wins in trends,
   whipsawed in chop.
2. **Mean reversion** — RSI(14) oversold bounce + hard 5% stop. Wins in ranges,
   dangerous in strong downtrends (hence the stop).
3. **Breakout** — Donchian 20-high entry / 10-low trailing exit + volume filter.
   Catches big moves, suffers fakeouts.

No strategy wins everywhere — that's the whole reason to run all three and pick
per-market based on backtests.

## Architecture
```
run.py            entry point (--paper works offline; --live is a skeleton)
backtester.py     standalone: validate strategies on history before anything live
bot/
  strategies.py   indicators + the 3 strategies (shared by backtest AND live)
  risk.py         position sizing, daily loss limit, hard kill switch
  brokers.py      PaperBroker (works) + CcxtBroker + IGBroker (live adapters)
  data.py         unified feed (ccxt + IG) + synthetic offline fallback
  engine.py       one-bar tick: data -> signal -> risk -> execute
```
The engine is identical in paper and live — only the broker + data source swap.

## Build roadmap (for Claude Code)
- [x] `git init`, commit this scaffold, add `.gitignore` (`.env`, `__pycache__`, `*.pyc`)
- [x] **Tests**: pytest suite for strategies, risk, paper broker, engine, state,
      notify and the live wiring (run `pytest -q`) — guards the money-critical logic
- [ ] **Validate**: run `backtester.py` on real BTC/ETH across bull/bear/chop;
      extend it to pull IG metal candles and backtest gold/silver too
- [x] **Live data**: `run_live()` loops per venue — fetches the latest *closed*
      bar per market, calls `engine.step()`, sleeps `timeframe` (`bot/live.py`).
      `--once` runs a single cycle for cron/smoke tests.
- [~] **Crypto live**: `CcxtBroker` wired into the loop from `.env`; still needs a
      tiny-size test on a real key (withdrawals disabled, IP-whitelisted)
- [~] **Metals live**: `IGBroker` wired (demo by default); still needs the **demo**
      account run — confirm current gold/silver epics, tune size (£/point) + stops
- [x] **Alerts**: `bot/notify.py` Telegram push on every BUY/SELL/halt (console
      fallback when `TELEGRAM_*` unset); never crashes the loop on send failure
- [x] **State persistence**: `bot/state.py` saves kill-switch + stops to atomic
      JSON each cycle; restart restores *today's* halt state, ignores stale days
- [ ] **Deploy**: cheap VPS or Raspberry Pi, run as a service, log to file
- [ ] **Harden**: reconnect logic, exchange/broker downtime handling, rate limits.
      Per-market fetch/step errors are already isolated so one bad feed can't
      stop the others; the per-venue `open_count()` feeds the max-open gate.

> `[~]` = code wired and unit-tested offline, but still needs a real
> demo/tiny-size run with live credentials before trusting it with money.

## Security (non-negotiable)
- Crypto keys: **trade-only, withdrawals disabled, IP-whitelisted**
- Secrets in `.env` (git-ignored) or a secrets manager — never committed
- Keep the `RiskManager` daily loss limit on at all times
- Start every live phase on DEMO / smallest size; scale only on proven behaviour

## Honest note
Automation removes emotional and execution errors — it does **not** create
edge. The strategy still has to genuinely work. Prove it: backtest → paper →
demo → tiny live, in that order. A winning backtest means "worth a small test",
never "this prints money".
```
