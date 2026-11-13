"""Read-only IG connection check. Places NO orders.

    python -m tools.ig_check

Reads IG_* from .env and:
  1. logs in (demo unless IG_DEMO=false),
  2. lists the accounts and balances,
  3. searches the spread-bet (DFB) epics for gold, silver and US crude,
  4. prints each market's minimum deal size and the capital that implies at
     the bot's sizing (each IG market gets 1/3 of the IG account),
  5. pulls a few daily candles to prove the price feed works.
Secrets are never printed.
"""
from __future__ import annotations

import os
import sys

SEARCHES = {"GOLD": "Spot Gold", "SILVER": "Spot Silver", "OIL": "Oil - US Crude"}
IG_MARKETS = 3


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    missing = [k for k in ("IG_API_KEY", "IG_IDENTIFIER", "IG_PASSWORD") if not os.getenv(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")


def pick_epic(results):
    """Prefer the daily-funded bet (expiry DFB) over futures-style expiries."""
    dfb = [m for m in results if m.get("expiry") == "DFB"]
    return (dfb or results or [None])[0]


def main():
    load_env()
    from bot.brokers import IGBroker
    from bot.data import fetch_metal_ig

    demo = os.getenv("IG_DEMO", "true").lower() != "false"
    print(f"Logging in to IG {'DEMO' if demo else 'LIVE'} as {os.environ['IG_IDENTIFIER']} ...")
    ig = IGBroker(os.environ["IG_API_KEY"], os.environ["IG_IDENTIFIER"],
                  os.environ["IG_PASSWORD"], demo=demo)
    print("  login OK\n")

    print("Accounts:")
    accounts = ig._call("GET", "/accounts")["accounts"]
    for a in accounts:
        b = a["balance"]
        print(f"  {'*' if a.get('preferred') else ' '} {a['accountName']:<24} "
              f"{a['accountType']:<10} {a.get('currency', '')} "
              f"balance {b.get('balance')}  P/L {b.get('profitLoss')}")
    print("  (* = preferred account the bot trades)\n")

    print("Markets:")
    found = {}
    for name, term in SEARCHES.items():
        results = ig._call("GET", "/markets", params={"searchTerm": term})["markets"]
        m = pick_epic(results)
        if not m:
            print(f"  {name:<7} no market found for '{term}'")
            continue
        epic = m["epic"]
        detail = ig._call("GET", f"/markets/{epic}", version="3")
        rules = detail["dealingRules"]
        snap = detail["snapshot"]
        price = ((snap.get("bid") or 0) + (snap.get("offer") or 0)) / 2
        min_size = float(rules["minDealSize"]["value"])
        need_trade = min_size * price
        found[name] = epic
        print(f"  {name:<7} {epic:<28} {m['instrumentName']} (expiry {m.get('expiry')})")
        print(f"          price ~{price:,.2f} · status {snap.get('marketStatus')} · "
              f"min size £{min_size}/pt -> min trade ~£{need_trade:,.0f} "
              f"-> IG account needs ~£{need_trade * IG_MARKETS:,.0f}")
        others = [r["epic"] for r in results if r is not m][:3]
        if others:
            print(f"          other matches: {', '.join(others)}")
    print()

    print("Daily candles:")
    for name, epic in found.items():
        df = fetch_metal_ig(ig, epic, resolution="DAY", limit=5)
        print(f"  {name:<7} {len(df)} bars, last close {df.close.iloc[-1]:,.2f} "
              f"({df.index[-1].date()})")

    print("\nPut these epics in run.py MARKETS:")
    for name, epic in found.items():
        print(f"  {name}: {epic}")


if __name__ == "__main__":
    main()
