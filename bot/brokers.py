"""Execution adapters. One common interface, three implementations:

    PaperBroker  -> simulated fills, fully working, used for testing/paper.
    CcxtBroker   -> live crypto via ccxt (Kraken for a UK account), limit orders.
    IGBroker     -> live gold/silver/oil spread bets via IG's REST API.

Live adapters return a normalised fill dict {units, price, cost, commission}
or None when nothing was traded; the reason is left in `last_reject`.
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

    def open_count(self) -> int:
        """Number of currently open positions (for the max-open risk gate).
        Default works for brokers that track positions in a local dict;
        venue-backed adapters override to query the account."""
        return len(getattr(self, "positions", {}))


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
        return {"symbol": symbol, "side": "buy", "price": fill, "units": units,
                "cost": stake, "commission": stake * self.fee}

    def close(self, symbol, price):
        p = self.positions.pop(symbol, None)
        if not p:
            return None
        fill = price * (1 - self.slip)
        gross = p["units"] * fill
        proceeds = gross * (1 - self.fee)
        self.cash += proceeds
        self.closed.append(proceeds / p["cost"] - 1)
        return {"symbol": symbol, "side": "sell", "price": fill,
                "pnl": proceeds - p["cost"],
                "pnl_pct": proceeds / p["cost"] - 1,
                # both legs' fees: entry fee on cost + exit fee on proceeds
                "commission": p["cost"] * self.fee + gross * self.fee}


# --------------------------------------------------------------------------- #
def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class CcxtBroker(Broker):
    """Live crypto via ccxt (Kraken for a UK account). Keys come from env with
    withdrawals DISABLED.

    Orders default to post-only LIMIT orders at the best bid/ask, which rest on
    the book and pay the maker fee (Kraken base: 0.40% vs 0.80% taker). Research
    showed this is worth ~3-4% a year on the crypto sleeves.
      - BUY: if nothing fills within `fill_timeout`, the order is cancelled and
        the entry is skipped; the strategy re-evaluates on the next bar.
      - SELL: tries a limit first, then sells whatever is left at market, so an
        exit always completes.
    """

    def __init__(self, exchange, api_key=None, secret=None, quote="USDT", ex=None,
                 order_type="limit", fill_timeout=120, poll=5, sleep=None):
        if ex is None:
            import ccxt
            ex = getattr(ccxt, exchange)({
                "apiKey": api_key, "secret": secret, "enableRateLimit": True})
        import time
        self.ex = ex
        self.quote = quote
        self.order_type = order_type
        self.fill_timeout = fill_timeout
        self.poll = poll
        self._sleep = sleep or time.sleep
        self.last_reject = None

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

    def _amount(self, symbol, units):
        fn = getattr(self.ex, "amount_to_precision", None)
        return float(fn(symbol, units)) if fn else units

    def _limit(self, side, symbol, units):
        """Post-only limit at the touch; wait for a fill, cancel the rest.
        Returns the final order (possibly partly or not filled) or None if the
        exchange refused it."""
        book = self.ex.fetch_order_book(symbol, limit=5)
        px = book["bids"][0][0] if side == "buy" else book["asks"][0][0]
        try:
            order = self.ex.create_order(symbol, "limit", side,
                                         self._amount(symbol, units), px,
                                         {"postOnly": True})
        except Exception as e:                     # e.g. post-only would cross
            self.last_reject = f"limit {side} refused: {e}"
            return None
        waited = 0
        while waited < self.fill_timeout:
            o = self.ex.fetch_order(order["id"], symbol)
            if o.get("status") == "closed":
                return o
            self._sleep(self.poll)
            waited += self.poll
        try:
            self.ex.cancel_order(order["id"], symbol)
        except Exception:
            pass                                   # may have filled meanwhile
        return self.ex.fetch_order(order["id"], symbol)

    @staticmethod
    def _fills(*orders):
        """Merge one or more ccxt orders into units / avg price / cost / fees."""
        units = cost = fees = 0.0
        for o in orders:
            if not o:
                continue
            f = _num(o.get("filled"))
            avg = _num(o.get("average")) or _num(o.get("price"))
            units += f
            cost += _num(o.get("cost")) or f * avg
            fees += _num((o.get("fee") or {}).get("cost"))
        if units <= 0:
            return None
        return {"units": units, "price": cost / units, "cost": cost,
                "commission": fees}

    def buy(self, symbol, stake, price, stop=None):
        self.last_reject = None
        units = stake / price
        if self.order_type == "market":
            return self._fills(self.ex.create_market_buy_order(
                symbol, self._amount(symbol, units)))
        res = self._fills(self._limit("buy", symbol, units))
        if res is None and not self.last_reject:
            self.last_reject = (f"limit buy not filled in {self.fill_timeout}s; "
                                "will re-check next bar")
        return res

    def close(self, symbol, price):
        pos = self.position(symbol)
        if not pos:
            return None
        units = pos["units"]
        first = self._limit("sell", symbol, units) if self.order_type == "limit" else None
        left = units - _num((first or {}).get("filled"))
        rest = None
        if left > units * 0.001:                   # exits must complete
            rest = self.ex.create_market_sell_order(symbol, self._amount(symbol, left))
        return self._fills(first, rest)


# --------------------------------------------------------------------------- #
class IGBroker(Broker):
    """Live gold/silver/oil via IG spread betting REST API.

    Auth: POST /session with X-IG-API-KEY + identifier/password returns CST and
    X-SECURITY-TOKEN headers used on every request. Tokens expire, so a 401
    triggers one automatic re-login. Requests are spaced `min_interval` apart to
    stay inside IG's per-minute API limits.

    Sizing: a spread bet's size is £ per point, so a notional stake of £S on a
    market priced P points is S / P £/point. Sizes below IG's minimum deal
    size for the market are refused (the bot alerts instead of over-betting).
    Every order is confirmed via /confirms; a rejected deal records nothing.
    Epics differ between demo/live and change over time — confirm in IG's API
    companion before trading.
    """

    BASE_DEMO = "https://demo-api.ig.com/gateway/deal"
    BASE_LIVE = "https://api.ig.com/gateway/deal"

    def __init__(self, api_key, identifier, password, demo=True, session=None,
                 min_interval=1.0, sleep=None, clock=None, max_round_up=1.0):
        import time
        if session is None:
            import requests
            session = requests.Session()
        self.s = session
        self.base = self.BASE_DEMO if demo else self.BASE_LIVE
        self._creds = {"identifier": identifier, "password": password}
        self.min_interval = min_interval
        # >1 lets a too-small order round UP to IG's minimum deal size, as long
        # as that minimum is at most this multiple of the intended stake.
        # 1.0 (default) never bets more than the risk manager asked for.
        self.max_round_up = max_round_up
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._last = None
        self._min_size = {}
        self.last_reject = None
        self.s.headers.update({
            "X-IG-API-KEY": api_key, "Content-Type": "application/json",
            "Accept": "application/json; charset=UTF-8"})
        self._login()

    # ---- plumbing ------------------------------------------------------ #
    def _throttle(self):
        now = self._clock()
        if self._last is not None:
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last = now

    def _login(self):
        self._throttle()
        r = self.s.request("POST", f"{self.base}/session", json=self._creds,
                           headers={"Version": "2"})
        r.raise_for_status()
        self.s.headers.update({"CST": r.headers["CST"],
                               "X-SECURITY-TOKEN": r.headers["X-SECURITY-TOKEN"]})

    def _call(self, method, path, version="1", **kw):
        headers = {"Version": version, **kw.pop("headers", {})}
        for attempt in (1, 2):
            self._throttle()
            r = self.s.request(method, f"{self.base}{path}", headers=headers, **kw)
            if r.status_code == 401 and attempt == 1:
                self._login()                      # session expired: log in again
                continue
            r.raise_for_status()
            return r.json() if r.content else {}

    def _confirm(self, deal_ref):
        return self._call("GET", f"/confirms/{deal_ref}")

    # ---- account ------------------------------------------------------- #
    def equity(self, marks):
        accounts = self._call("GET", "/accounts")["accounts"]
        acc = next((a for a in accounts if a.get("preferred")), accounts[0])
        bal = acc["balance"]
        return _num(bal.get("balance")) + _num(bal.get("profitLoss"))

    def _positions(self):
        return self._call("GET", "/positions", version="2")["positions"]

    def position(self, symbol):  # symbol == IG epic
        for d in self._positions():
            if d["market"]["epic"] == symbol:
                return {"units": d["position"]["size"],
                        "dealId": d["position"]["dealId"]}
        return None

    def open_count(self):
        return len(self._positions())

    def min_size(self, epic):
        if epic not in self._min_size:
            rules = self._call("GET", f"/markets/{epic}", version="3")["dealingRules"]
            self._min_size[epic] = _num(rules["minDealSize"]["value"])
        return self._min_size[epic]

    # ---- orders -------------------------------------------------------- #
    def buy(self, symbol, stake, price, stop=None):
        self.last_reject = None
        size = round(stake / price, 2)              # £ per point
        minimum = self.min_size(symbol)
        if size < minimum:
            if minimum * price <= stake * self.max_round_up:
                size = minimum                      # opted-in: bet IG's minimum
            else:
                self.last_reject = (f"size £{size}/pt below IG minimum £{minimum}/pt "
                                    f"(needs ~£{minimum * price:,.0f} per trade); skipped")
                return None
        body = {"epic": symbol, "direction": "BUY", "size": size,
                "orderType": "MARKET", "currencyCode": "GBP",
                "forceOpen": True, "guaranteedStop": False, "expiry": "DFB"}
        # Server-side stop so a bot crash can't leave a leveraged position
        # unprotected. IG wants a DISTANCE in points below entry.
        if stop and price and stop < price:
            body["stopDistance"] = round(price - stop, 2)
        ref = self._call("POST", "/positions/otc", version="2", json=body)["dealReference"]
        conf = self._confirm(ref)
        if conf.get("dealStatus") != "ACCEPTED":
            self.last_reject = f"IG rejected the deal: {conf.get('reason', 'unknown')}"
            return None
        level = _num(conf.get("level"), price)
        return {"units": size, "price": level, "cost": size * level,
                "commission": 0.0, "dealId": conf.get("dealId")}

    def close(self, symbol, price):
        pos = self.position(symbol)
        if not pos:
            return None
        body = {"dealId": pos["dealId"], "direction": "SELL",
                "size": pos["units"], "orderType": "MARKET"}
        ref = self._call("POST", "/positions/otc", json=body,
                         headers={"_method": "DELETE"})["dealReference"]
        conf = self._confirm(ref)
        if conf.get("dealStatus") != "ACCEPTED":
            raise RuntimeError(f"IG refused to close {symbol}: {conf.get('reason')}")
        level = _num(conf.get("level"), price)
        return {"units": pos["units"], "price": level, "commission": 0.0}
