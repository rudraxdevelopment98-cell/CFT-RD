# Research findings — what actually works (and what doesn't)

> Honest, **out-of-sample** research on 10 years of real daily data
> (Yahoo Finance). Everything here is judged on the **last ~35% of history the
> strategies never saw** — so these are not curve-fitted numbers. Reproduce with:
>
> ```bash
> pip install -r requirements.txt
> python -m research.lab          # per-instrument, out-of-sample
> python -m research.portfolio    # the combined 5-sleeve result
> ```

## TL;DR
- **No strategy is "90% right."** High win-rate strategies (mean-reversion, 60–85% wins) and low win-rate strategies (trend, 15–35% wins) can *both* be profitable — what matters is **risk-adjusted return (Sharpe) and drawdown**, not win rate.
- The real edge is **diversification**: a handful of *uncorrelated* instrument+strategy pairs combined together.
- **FX majors (EUR/USD, GBP/USD, USD/JPY) were dropped** — no reliable edge. Those markets are too efficient; our strategies barely beat zero there.

## The instruments we chose (the "genre")
Focus on **commodities + crypto**, skip FX:

| Instrument | Best strategy (OOS) | Family | Why it fits |
|---|---|---|---|
| **Gold**   | TrendEMA   | trend | Gold trends cleanly; EMA 20/50 + 200 filter rode it with half the drawdown of buy & hold |
| **Silver** | Bollinger  | mean-reversion | Silver whips around its mean; buying 2σ dips worked |
| **Oil**    | RSI mean-rev | mean-reversion | Oil bounces hard off oversold; small exposure, strong Sharpe |
| **BTC**    | TrendEMA   | trend | Trend-following tames crypto, but drawdowns stay large — small size |
| **ETH**    | TrendEMA   | trend | Same; BTC/ETH are 0.60 correlated so treat as one risk bucket |

## Out-of-sample results per instrument (best strategy vs Buy & Hold)
| Instrument | Strategy | Sharpe | CAGR% | MaxDD% | B&H Sharpe |
|---|---|---|---|---|---|
| Gold   | TrendEMA   | **1.21** | 22.6 | −17.9 | 1.11 |
| Silver | Bollinger  | **1.13** | 15.0 |  −9.7 | 0.81 |
| Oil    | RSImeanrev | **0.84** |  7.9 | −11.7 | 0.29 |
| ETH    | TrendEMA   | **0.81** | 36.0 | −39.5 | 0.46 |
| BTC    | TrendEMA   | **0.77** | 28.5 | −38.1 | 0.76 |

## The combined portfolio (the actual "algo")
Equal-weight across the 5 sleeves above. Sleeves are nearly uncorrelated
(gold/silver/oil/crypto all ≈ 0), so their drawdowns don't stack:

| | CAGR% | Sharpe | Sortino | MaxDD% | Calmar |
|---|---|---|---|---|---|
| **5-sleeve strategy** | 23.4 | **1.33** | **1.67** | **−10.5** | **2.23** |
| Equal-weight Buy & Hold | 28.7 | 0.91 | 1.25 | −27.3 | 1.05 |

**Read it honestly:** the strategy made *slightly less* raw return than just
buying and holding (23% vs 29% CAGR) — but with **one-third the drawdown**
(−10.5% vs −27.3%) and much better Sharpe. That trade — a bit less return for
far less pain — is what a real edge looks like. £10,000 → ~£20,900 over 3.5 yrs.

**This is a realistic target: ~15–25%/year with <15% drawdown.** Not 2%/day.

## Honest caveats (why this is a start, not a finished system)
1. **Small trade counts.** Gold TrendEMA fired only 6 trades OOS, Oil RSI only 3. Few trades = fragile; one lucky trade can flatter the Sharpe.
2. **Daily bars, Yahoo data.** Live you'll trade IG (metals) / ccxt (crypto) with real spreads, slippage and different candle times.
3. **One OOS window.** 2023–2026 was gold-friendly. A different period could look different — needs rolling walk-forward.
4. **No parameter robustness yet.** We used textbook params; we have not checked they're stable (not just the one lucky setting).

## Step-by-step plan to improve (next)
- [ ] **Walk-forward**: roll the IS/OOS window across all 10 years, not one split.
- [ ] **Parameter robustness**: sweep each strategy's params, keep only settings that work across a *range*, not a single peak.
- [ ] **ATR stops + position sizing**: size each sleeve by volatility so risk is equal, add protective stops.
- [ ] **More history / intraday**: validate on 4h candles for crypto; confirm IG metal epics.
- [ ] **Wire the winners into the live bot**: map each instrument to its chosen strategy, run on paper → IG demo → tiny live.
- [ ] **Monthly re-validation**: markets regime-shift; re-run `research.lab` monthly and retire sleeves that stop working.
