"""Live adapters against fake exchanges: Kraken limit orders, IG sizing,
deal confirmation, re-login, throttling, and DB/broker reconciliation."""
import pytest

from bot.brokers import CcxtBroker, IGBroker
from bot.database import Database
from bot.engine import Engine
from bot.live import Venue
from bot.risk import RiskManager
from bot import strategies
from conftest import ohlcv


# --------------------------------------------------------------------------- #
# Kraken / ccxt
# --------------------------------------------------------------------------- #
class FakeExchange:
    """Order book at 99/101. `fill` controls how much of a limit order fills."""

    def __init__(self, fill=1.0, refuse_post_only=False):
        self.fill = fill
        self.refuse_post_only = refuse_post_only
        self.created, self.cancelled, self.market = [], [], []
        self.balance = {"GBP": 1000.0, "BTC": 0.0}

    def fetch_order_book(self, symbol, limit=5):
        return {"bids": [[99.0, 1]], "asks": [[101.0, 1]]}

    def create_order(self, symbol, type_, side, amount, price, params):
        if self.refuse_post_only:
            raise RuntimeError("post-only order would cross")
        o = {"id": str(len(self.created)), "side": side, "amount": amount,
             "price": price, "params": params}
        self.created.append(o)
        return o

    def fetch_order(self, oid, symbol):
        o = self.created[int(oid)]
        filled = o["amount"] * self.fill
        return {"id": oid, "status": "closed" if self.fill >= 1 else "open",
                "filled": filled, "average": o["price"], "cost": filled * o["price"],
                "fee": {"cost": filled * o["price"] * 0.004}}

    def cancel_order(self, oid, symbol):
        self.cancelled.append(oid)

    def create_market_sell_order(self, symbol, amount):
        self.market.append(("sell", amount))
        return {"filled": amount, "average": 98.0, "cost": amount * 98.0,
                "fee": {"cost": amount * 98.0 * 0.008}}

    def create_market_buy_order(self, symbol, amount):
        self.market.append(("buy", amount))
        return {"filled": amount, "average": 101.5, "cost": amount * 101.5,
                "fee": {"cost": 0.8}}

    def fetch_balance(self):
        return {"total": self.balance}


def _ccxt(ex, **kw):
    return CcxtBroker("kraken", ex=ex, quote="GBP", fill_timeout=10, poll=5,
                      sleep=lambda s: None, **kw)


def test_limit_buy_is_post_only_at_the_bid_and_pays_maker_fee():
    ex = FakeExchange(fill=1.0)
    res = _ccxt(ex).buy("BTC/GBP", 100.0, 100.0)
    order = ex.created[0]
    assert order["side"] == "buy" and order["price"] == 99.0
    assert order["params"] == {"postOnly": True}
    assert res["units"] == pytest.approx(1.0) and res["price"] == 99.0
    assert res["commission"] == pytest.approx(99.0 * 0.004)
    assert ex.market == []                              # no taker fallback on entries


def test_unfilled_limit_buy_is_cancelled_and_skipped():
    ex = FakeExchange(fill=0.0)
    b = _ccxt(ex)
    assert b.buy("BTC/GBP", 100.0, 100.0) is None
    assert ex.cancelled == ["0"] and "not filled" in b.last_reject


def test_post_only_refusal_is_reported():
    b = _ccxt(FakeExchange(refuse_post_only=True))
    assert b.buy("BTC/GBP", 100.0, 100.0) is None
    assert "refused" in b.last_reject


def test_close_tries_limit_then_sells_the_rest_at_market():
    ex = FakeExchange(fill=0.4)
    ex.balance["BTC"] = 2.0
    res = _ccxt(ex).close("BTC/GBP", 100.0)
    assert ex.created[0]["side"] == "sell" and ex.created[0]["price"] == 101.0
    assert ex.market == [("sell", pytest.approx(1.2))]   # 60% left -> market
    assert res["units"] == pytest.approx(2.0)
    assert res["price"] == pytest.approx((0.8 * 101 + 1.2 * 98) / 2)


def test_market_mode_uses_market_orders():
    ex = FakeExchange()
    res = _ccxt(ex, order_type="market").buy("BTC/GBP", 101.5, 100.0)
    assert ex.market[0][0] == "buy" and res["price"] == 101.5


def test_engine_alerts_when_a_buy_is_not_placed():
    strategies.REGISTRY["go"] = lambda df: ("enter", None)
    try:
        notes = []
        ex = FakeExchange(fill=0.0)
        risk = RiskManager(per_trade_pct=0.5)
        risk.new_day(1000)
        eng = Engine(_ccxt(ex), risk, [], notify=notes.append)
        eng.step({"name": "BTC", "symbol": "BTC/GBP", "strategy": "go"},
                 ohlcv([100] * 5))
        assert any("BTC not placed" in n and "not filled" in n for n in notes)
    finally:
        strategies.REGISTRY.pop("go", None)


# --------------------------------------------------------------------------- #
# IG
# --------------------------------------------------------------------------- #
class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.content = b"x"

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeIG:
    def __init__(self, min_size=0.5, accept=True, expire_once=False):
        self.headers = {}
        self.calls = []
        self.min_size = min_size
        self.accept = accept
        self.expire_once = expire_once
        self.logins = 0
        self.positions = []

    def request(self, method, url, json=None, headers=None, params=None):
        path = url.split("/gateway/deal")[1]
        self.calls.append((method, path, json, headers))
        if path == "/session":
            self.logins += 1
            return Resp(headers={"CST": f"c{self.logins}", "X-SECURITY-TOKEN": "t"})
        if self.expire_once:
            self.expire_once = False
            return Resp(401)
        if path.startswith("/markets/"):
            return Resp(body={"dealingRules": {"minDealSize": {"value": self.min_size}}})
        if path == "/positions/otc":
            return Resp(body={"dealReference": "REF1"})
        if path.startswith("/confirms/"):
            if self.accept:
                return Resp(body={"dealStatus": "ACCEPTED", "level": 2401.5, "dealId": "D1"})
            return Resp(body={"dealStatus": "REJECTED", "reason": "MARKET_CLOSED"})
        if path == "/positions":
            return Resp(body={"positions": self.positions})
        if path.startswith("/prices/"):
            self.price_params = params
            bar = lambda d, px: {"snapshotTimeUTC": d, "lastTradedVolume": 1,
                                 **{k: {"bid": px - 1, "ask": px + 1} for k in
                                    ("openPrice", "highPrice", "lowPrice", "closePrice")}}
            return Resp(body={"prices": [bar("2026-01-02T00:00:00", 110),
                                         bar("2026-01-01T00:00:00", 100)]})
        if path == "/accounts":
            return Resp(body={"accounts": [
                {"preferred": False, "balance": {"balance": 1, "profitLoss": 0}},
                {"preferred": True, "balance": {"balance": 5000, "profitLoss": -120}}]})
        raise AssertionError(path)


def _ig(sess, **kw):
    return IGBroker("key", "user", "pw", session=sess, min_interval=0,
                    sleep=lambda s: None, **kw)


def test_ig_size_is_stake_over_price_with_server_stop_and_dfb():
    sess = FakeIG(min_size=0.5)
    res = _ig(sess).buy("CS.D.GOLD", 2400.0, 2400.0, stop=2300.0)
    body = next(c[2] for c in sess.calls if c[1] == "/positions/otc")
    assert body["size"] == 1.0                          # £2400 notional / 2400 pts
    assert body["stopDistance"] == 100.0 and body["expiry"] == "DFB"
    assert res == {"units": 1.0, "price": 2401.5, "cost": 2401.5,
                   "commission": 0.0, "dealId": "D1"}


def test_ig_refuses_size_below_minimum():
    sess = FakeIG(min_size=0.5)
    b = _ig(sess)
    assert b.buy("CS.D.GOLD", 240.0, 2400.0) is None    # 0.1 £/pt < 0.5
    assert "below IG minimum" in b.last_reject
    assert not any(c[1] == "/positions/otc" for c in sess.calls)


def test_ig_round_up_to_minimum_only_when_opted_in_and_close():
    sess = FakeIG(min_size=1.0)
    b = _ig(sess, max_round_up=1.5)
    res = b.buy("CS.D.GOLD", 3333.0, 3900.0)            # wants 0.85, min 1.0 (1.17x)
    assert res["units"] == 1.0
    assert b.buy("CS.D.GOLD", 2000.0, 3900.0) is None   # min would be 1.95x -> refused
    assert "below IG minimum" in b.last_reject


def test_ig_rejected_deal_records_nothing():
    b = _ig(FakeIG(accept=False))
    assert b.buy("CS.D.GOLD", 2400.0, 2400.0) is None
    assert "MARKET_CLOSED" in b.last_reject


def test_ig_relogs_in_once_on_expired_session():
    sess = FakeIG()
    b = _ig(sess)
    sess.expire_once = True
    assert b.equity({}) == 4880                          # preferred: balance + P/L
    assert sess.logins == 2


def test_ig_prices_disable_paging_and_sort_oldest_first():
    from bot.data import fetch_metal_ig
    sess = FakeIG()
    df = fetch_metal_ig(_ig(sess), "CS.D.GOLD", resolution="DAY", limit=300)
    assert sess.price_params["pageSize"] == 0 and sess.price_params["max"] == 300
    assert list(df.close) == [100, 110]                 # sorted by time, mid price


def test_ig_throttles_requests():
    sleeps, t = [], [0.0]
    sess = FakeIG()
    b = IGBroker("k", "u", "p", session=sess, min_interval=1.0,
                 sleep=sleeps.append, clock=lambda: t[0])
    b.equity({})
    assert sleeps == [1.0]                               # login, then 1s gap


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
class LiveLike:
    """A non-paper broker (no cash/positions attributes) for reconcile tests."""

    def __init__(self, held=None):
        self.held = held or {}

    def position(self, sym):
        return {"units": self.held[sym]} if sym in self.held else None

    def equity(self, marks):
        return 1000.0

    def open_count(self):
        return len(self.held)


def _live_venue(db, broker, notes):
    return Venue("ig", broker, RiskManager(), [
        {"name": "GOLD", "symbol": "G", "strategy": "trend"},
        {"name": "OIL", "symbol": "O", "strategy": "meanrev"}],
        fetch=lambda m: ohlcv([100] * 10), db=db, notify=notes.append,
        retry_sleep=lambda s: None)


def test_reconcile_records_positions_closed_at_the_broker(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.open_position(venue="ig", symbol="G", market="GOLD", strategy="trend",
                     size=1, cost=100, entry_price=100, stop_loss=95)
    db.update_marks({"G": 96})
    notes = []
    v = _live_venue(db, LiveLike(), notes)
    v.engine.stops["G"] = 95
    v.reconcile()
    [t] = db.trades()
    assert t["reason"].startswith("closed at broker") and t["exit_price"] == 96
    assert db.positions() == [] and "G" not in v.engine.stops
    assert any("closed at the broker" in n for n in notes)


def test_reconcile_warns_once_about_untracked_positions(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    notes = []
    v = _live_venue(db, LiveLike({"O": 2.0}), notes)
    v.reconcile()
    v.reconcile()
    assert sum("did not open" in n for n in notes) == 1
    assert db.trades() == []
