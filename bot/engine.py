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

    def step(self, market, df):
        """Process the latest bar of one market. df = recent OHLCV window."""
        sym = market["symbol"]
        strat = REGISTRY[market["strategy"]]
        signal, stop_pct = strat(df)
        price = df.close.iloc[-1]
        pos = self.broker.position(sym)
        marks = {sym: price}

        # ---- risk gate: daily kill switch ----
        equity = self.broker.equity(marks)
        if not self.risk.check_daily_limit(equity):
            if pos:                                   # flatten on halt
                self._do_close(sym, price, "daily-loss halt")
            return

        # ---- stop-loss check (paper broker tracks stop) ----
        if pos and pos.get("stop") and price <= pos["stop"]:
            self._do_close(sym, price, "stop-loss")
            return

        # ---- act on signal ----
        if pos and signal == "exit":
            self._do_close(sym, price, "exit signal")
        elif not pos and signal == "enter":
            open_n = len(getattr(self.broker, "positions", {}))
            if self.risk.can_open(open_n):
                stake = self.risk.stake(equity)
                stop = price * (1 - stop_pct) if stop_pct else None
                self.broker.buy(sym, stake, price, stop=stop)
                self.notify(f"BUY {market['name']} @ {price:.2f} "
                            f"stake {stake:.2f}")

    def _do_close(self, sym, price, reason):
        res = self.broker.close(sym, price)
        if res:
            pnl = res.get("pnl_pct")
            tail = f" pnl {pnl*100:+.2f}%" if pnl is not None else ""
            self.notify(f"SELL {sym} @ {price:.2f} ({reason}){tail}")
