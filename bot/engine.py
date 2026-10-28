"""The trading loop. `step()` processes one closed bar for one market.
Identical logic in paper and live — only the broker + data source change."""
from .strategies import REGISTRY


class Engine:
    def __init__(self, broker, risk, markets, notify=None):
        # markets: list of dicts {name, symbol, strategy}
        self.broker = broker
        self.risk = risk
        self.markets = markets
        self.notify = notify or (lambda m: None)
        # Stops are tracked HERE, client-side, so they work for every broker.
        # Live adapters (ccxt / IG) don't echo a stop back on position(), so
        # relying on the broker alone would leave live positions unprotected.
        self.stops = {}                               # symbol -> stop price

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
        equity = self.broker.equity(marks)
        if not self.risk.check_daily_limit(equity):
            if pos:                                   # flatten on halt
                self._do_close(sym, price, "daily-loss halt")
            return

        # ---- stop-loss check (client-side; falls back to broker-stored stop) ----
        stop = self.stops.get(sym)
        if stop is None and pos:
            stop = pos.get("stop")
        if pos and stop and price <= stop:
            self._do_close(sym, price, "stop-loss")
            return

        # ---- act on signal ----
        if pos and signal == "exit":
            self._do_close(sym, price, "exit signal")
        elif not pos and signal == "enter":
            open_n = self.broker.open_count()
            if self.risk.can_open(open_n):
                stake = self.risk.stake(equity)
                stop_price = price * (1 - stop_pct) if stop_pct else None
                self.broker.buy(sym, stake, price, stop=stop_price)
                if stop_price:
                    self.stops[sym] = stop_price
                self.notify(f"BUY {market['name']} @ {price:.2f} "
                            f"stake {stake:.2f}"
                            + (f" stop {stop_price:.2f}" if stop_price else ""))

    def _do_close(self, sym, price, reason):
        res = self.broker.close(sym, price)
        self.stops.pop(sym, None)                     # forget the stop once flat
        if res:
            pnl = res.get("pnl_pct")
            tail = f" pnl {pnl*100:+.2f}%" if pnl is not None else ""
            self.notify(f"SELL {sym} @ {price:.2f} ({reason}){tail}")
