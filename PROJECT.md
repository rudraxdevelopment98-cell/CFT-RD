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
- [ ] `git init`, commit this scaffold, add `.gitignore` (`.env`, `__pycache__`, `*.pyc`)
- [ ] **Validate**: run `backtester.py` on real BTC/ETH across bull/bear/chop;
      extend it to pull IG metal candles and backtest gold/silver too
- [ ] **Live data**: implement the loop in `run_live()` — fetch latest *closed*
      bar per market, call `engine.step()`, `time.sleep(timeframe)`
- [ ] **Crypto live**: wire `CcxtBroker`, test on tiny size
- [ ] **Metals live**: wire `IGBroker` on the **demo** account; confirm current
      epics for gold/silver; tune spread-bet size (£/point) + stop distance
- [ ] **Alerts**: Telegram notify on every BUY/SELL/halt (token in `.env`)
- [ ] **State persistence**: save positions/equity to a file or SQLite so a
      restart doesn't lose track
- [ ] **Deploy**: cheap VPS or Raspberry Pi, run as a service, log to file
- [ ] **Harden**: reconnect logic, exchange/broker downtime handling, rate limits

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
