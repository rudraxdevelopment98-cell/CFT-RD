"""Trading-cost models per instrument, so backtests charge what the live
venues will actually charge.

All figures are ASSUMPTIONS (Nov 2026), written down here so they can be
checked against the venue's current fee page and changed in one place:

Kraken (BTC, ETH, spot):
    Kraken Pro base tier is 0.40% maker / 0.80% taker per fill (July 2026
    schedule). Limit orders that rest on the book pay maker. We add slippage.
    No overnight funding on spot.

IG spread betting (GOLD, SILVER, OIL):
    No commission; cost is the spread. Typical spot spreads: gold ~0.3 pt,
    silver ~2 cents, US crude ~2.8 pts, i.e. a few hundredths of a percent.
    A long bet held overnight pays funding of roughly SONIA + 2.5% a year on
    the position size. With SONIA assumed ~3.75% that is ~6.25% a year.

Each scenario maps instrument -> (cost_per_side, hold_cost_annual, bars_per_year).
"""

IG = {"GOLD", "SILVER", "OIL"}
CRYPTO = {"BTC", "ETH"}

# per-side cost = half the spread (or the fee) + slippage
SCENARIOS = {
    # what the original research assumed
    "old assumption": {
        "GOLD": (0.0005, 0.0, 252), "SILVER": (0.0005, 0.0, 252),
        "OIL": (0.0005, 0.0, 252),
        "BTC": (0.0010, 0.0, 365), "ETH": (0.0010, 0.0, 365),
    },
    # limit orders on Kraken (maker), typical IG spreads + funding
    "realistic": {
        "GOLD": (0.0003, 0.0625, 252), "SILVER": (0.0006, 0.0625, 252),
        "OIL": (0.0005, 0.0625, 252),
        "BTC": (0.0045, 0.0, 365), "ETH": (0.0045, 0.0, 365),
    },
    # market orders on Kraken (taker), wider spreads, higher funding
    "pessimistic": {
        "GOLD": (0.0006, 0.075, 252), "SILVER": (0.0012, 0.075, 252),
        "OIL": (0.0010, 0.075, 252),
        "BTC": (0.0090, 0.0, 365), "ETH": (0.0090, 0.0, 365),
    },
}


def cost_kwargs(instrument: str, scenario: str = "realistic") -> dict:
    per_side, hold, bars = SCENARIOS[scenario][instrument]
    return {"cost_per_side": per_side, "hold_cost_annual": hold,
            "bars_per_year": bars}
