"""Execution adapters. One common interface, three implementations:

    PaperBroker  -> simulated fills, fully working, used for testing/paper.
    CcxtBroker   -> live crypto via ccxt (Binance/Kraken/Bybit/...).
    IGBroker     -> live gold/silver spread bets via IG's REST API.

Live adapters are structured and commented; fill in credentials in .env and
the TODO order calls when you're ready to go from paper -> tiny live.
"""
from abc import ABC, abstractmethod


class Broker(ABC):
    @abstractmethod
    def equity(self, marks: dict) -> float: ...
    @abstractmethod
    def position(self, symbol): ...
    @abstractmethod
    def buy(self, symbol, stake, price): ...
    @abstractmethod
    def close(self, symbol, price): ...


# --------------------------------------------------------------------------- #
class PaperBroker(Broker):
    """Simulated broker with fees + slippage. The truth-teller before live."""

    def __init__(self, cash=10_000, fee=0.001, slip=0.0005):
        self.cash = cash
        self.fee, self.slip = fee, slip
        self.positions = {}   # symbol -> {'units','entry','stop'}
        self.closed = []      # list of trade return fractions

    def equity(self, marks):
        val = self.cash
        for sym, p in self.positions.items():
            val += p["units"] * marks.get(sym, p["entry"])
        return val

    def position(self, symbol):
        return self.positions.get(symbol)

    def buy(self, symbol, stake, price, stop=None):
        stake = min(stake, self.cash)
        if stake <= 0:
            return None
        fill = price * (1 + self.slip)
        units = (stake * (1 - self.fee)) / fill
        self.cash -= stake
        self.positions[symbol] = {"units": units, "entry": fill,
                                  "cost": stake, "stop": stop}
        return {"symbol": symbol, "side": "buy", "price": fill, "units": units}

    def close(self, symbol, price):
        p = self.positions.pop(symbol, None)
        if not p:
            return None
        fill = price * (1 - self.slip)
        proceeds = p["units"] * fill * (1 - self.fee)
        self.cash += proceeds
        self.closed.append(proceeds / p["cost"] - 1)
        return {"symbol": symbol, "side": "sell", "price": fill,
                "pnl_pct": proceeds / p["cost"] - 1}


# --------------------------------------------------------------------------- #
class CcxtBroker(Broker):
    """Live crypto. Wraps ccxt. Keys come from env (withdrawal DISABLED)."""

    def __init__(self, exchange, api_key, secret, quote="USDT"):
        import ccxt
        self.ex = getattr(ccxt, exchange)({
            "apiKey": api_key, "secret": secret, "enableRateLimit": True})
        self.quote = quote

    def equity(self, marks):
        bal = self.ex.fetch_balance()
        total = bal["total"].get(self.quote, 0)
        for sym, mk in marks.items():
            base = sym.split("/")[0]
            total += bal["total"].get(base, 0) * mk
        return total

    def position(self, symbol):
        base = symbol.split("/")[0]
        amt = self.ex.fetch_balance()["total"].get(base, 0)
        return {"units": amt} if amt and amt > 0 else None

    def buy(self, symbol, stake, price, stop=None):
        units = stake / price
        return self.ex.create_market_buy_order(symbol, units)   # live order

    def close(self, symbol, price):
        pos = self.position(symbol)
        if not pos:
            return None
        return self.ex.create_market_sell_order(symbol, pos["units"])


# --------------------------------------------------------------------------- #
class IGBroker(Broker):
    """Live gold/silver via IG spread betting REST API.

    Auth flow (one call at startup):
        POST /session  with X-IG-API-KEY header + identifier/password
        -> returns CST and X-SECURITY-TOKEN headers used on every request.
    Markets: 'CS.D.CFDGOLD.CFDGC.IP' (gold), 'CS.D.CFDSILVER.CFDSI.IP'
    (epics differ between demo/live and over time — confirm in IG's API
    companion / lightstreamer browser).
    """

    BASE_DEMO = "https://demo-api.ig.com/gateway/deal"
    BASE_LIVE = "https://api.ig.com/gateway/deal"

    def __init__(self, api_key, identifier, password, demo=True):
        import requests
        self.s = requests.Session()
        self.base = self.BASE_DEMO if demo else self.BASE_LIVE
        self.s.headers.update({
            "X-IG-API-KEY": api_key, "Content-Type": "application/json",
            "Accept": "application/json; charset=UTF-8", "Version": "2"})
        r = self.s.post(f"{self.base}/session",
                        json={"identifier": identifier, "password": password})
        r.raise_for_status()
        self.s.headers.update({
            "CST": r.headers["CST"],
            "X-SECURITY-TOKEN": r.headers["X-SECURITY-TOKEN"]})

    def equity(self, marks):
        acc = self.s.get(f"{self.base}/accounts").json()["accounts"][0]
        return acc["balance"]["balance"]

    def position(self, symbol):  # symbol == IG epic
        for d in self.s.get(f"{self.base}/positions").json()["positions"]:
            if d["market"]["epic"] == symbol:
                return {"units": d["position"]["size"],
                        "dealId": d["position"]["dealId"]}
        return None

    def buy(self, symbol, stake, price, stop=None):
        # stake -> spread-bet size (£/point). Sizing & stop distance need
        # tuning per market; start tiny on demo.
        body = {"epic": symbol, "direction": "BUY", "size": round(stake, 2),
                "orderType": "MARKET", "currencyCode": "GBP",
                "forceOpen": True, "guaranteedStop": False, "expiry": "-"}
        return self.s.post(f"{self.base}/positions/otc", json=body).json()

    def close(self, symbol, price):
        pos = self.position(symbol)
        if not pos:
            return None
        body = {"dealId": pos["dealId"], "direction": "SELL",
                "size": pos["units"], "orderType": "MARKET"}
        h = {"_method": "DELETE"}
        return self.s.post(f"{self.base}/positions/otc",
                           json=body, headers=h).json()
