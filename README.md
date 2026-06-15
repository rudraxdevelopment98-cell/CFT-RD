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
run.py            entry point (--paper works offline now; --live is a skeleton)
bot/
  strategies.py   indicators + 3 strategies (trend / meanrev / breakout)
  risk.py         position sizing, daily loss limit, kill switch
  brokers.py      PaperBroker (works) + CcxtBroker + IGBroker (live adapters)
  data.py         unified feed (ccxt + IG) with synthetic offline fallback
  engine.py       one-bar tick: data -> signal -> risk -> execute
```

## Quick start
```bash
pip install -r requirements.txt
python run.py --paper          # offline simulation, no keys needed
```

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
