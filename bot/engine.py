"""The trading loop. `step()` processes one closed bar for one market.
Identical logic in paper and live — only the broker + data source change."""
from .strategies import REGISTRY


class Engine:
    def __init__(self, broker, risk, markets, notify=None, db=None,
                 venue="default"):
        # markets: list of dicts {name, symbol, strategy}
        self.broker = broker
        self.risk = risk
        self.markets = markets
        self.notify = notify or (lambda m: None)
        # Every open/close is recorded here (bot/database.py) when given; the DB
        # write happens right after the broker call and before the alert, so the
        # database is the record of what the broker actually did.
        self.db = db
        self.venue = venue
        # Stops are tracked HERE, client-side, so they work for every broker.
        # Live adapters (ccxt / IG) don't echo a stop back on position(), so
        # relying on the broker alone would leave live positions unprotected.
        self.stops = {}                               # symbol -> stop price

    def _cash(self):
        return getattr(self.broker, "cash", None)

    def step(self, market, df, marks=None):
        """Process the latest bar of one market. df = recent OHLCV window.
        marks: latest price per symbol across the whole account, so the daily
        kill switch values *all* open positions, not just this one."""
        sym = market["symbol"]
        strat = REGISTRY[market["strategy"]]
        signal, stop_pct = strat(df)
        price = df.close.iloc[-1]
        pos = self.broker.position(sym)
        marks = {**(marks or {}), sym: price}         # this symbol's fresh close wins

        # ---- risk gate: daily kill switch (account-wide equity) ----
        # If equity can't be read, fail SAFE: no new trades this bar. Existing
        # stops are still enforced below with the price we do have.
        try:
            equity = self.broker.equity(marks)
        except Exception as e:
            self.notify(f"CRITICAL: equity unavailable for {market['name']} ({e}); "
                        "no new trades this bar")
            equity = None
        if equity is not None and not self.risk.check_daily_limit(equity):
            if pos:                                   # flatten on halt
                self._do_close(market, price, "daily-loss halt")
            return

        # ---- stop-loss check (client-side; falls back to broker-stored stop) ----
        stop = self.stops.get(sym)
        if stop is None and pos:
            stop = pos.get("stop")
        if pos and stop and price <= stop:
            self._do_close(market, price, "stop-loss")
            return

        # ---- act on signal ----
        if pos and signal == "exit":
            self._do_close(market, price, "exit signal")
        elif not pos and signal == "enter" and equity is not None:
            open_n = self.broker.open_count()
            if self.risk.can_open(open_n):
                stake = self.risk.stake(equity)
                stop_price = price * (1 - stop_pct) if stop_pct else None
                res = self.broker.buy(sym, stake, price, stop=stop_price)
                if res is None:                       # broker refused (e.g. no cash)
                    return
                if stop_price:
                    self.stops[sym] = stop_price
                if self.db:
                    info = res if isinstance(res, dict) else {}
                    fill = info.get("price", price)
                    self.db.open_position(
                        venue=self.venue, symbol=sym, market=market["name"],
                        strategy=market["strategy"],
                        size=info.get("units", stake / price),
                        cost=info.get("cost", stake), entry_price=fill,
                        stop_loss=stop_price, cash=self._cash())
                self.notify(f"BUY {market['name']} @ {price:.2f} "
                            f"stake {stake:.2f}"
                            + (f" stop {stop_price:.2f}" if stop_price else ""))

    def _do_close(self, market, price, reason):
        sym = market["symbol"]
        res = self.broker.close(sym, price)
        self.stops.pop(sym, None)                     # forget the stop once flat
        if res is None:
            return
        info = res if isinstance(res, dict) else {}
        if self.db:
            self.db.close_position(
                venue=self.venue, symbol=sym, exit_price=info.get("price", price),
                reason=reason, pnl=info.get("pnl"), pnl_pct=info.get("pnl_pct"),
                commission=info.get("commission"), cash=self._cash(),
                market=market["name"], strategy=market["strategy"])
        pnl = info.get("pnl_pct")
        tail = f" pnl {pnl*100:+.2f}%" if pnl is not None else ""
        self.notify(f"SELL {market['name']} @ {price:.2f} ({reason}){tail}")
