"""Live trading orchestration.

The roadmap step: "fetch the latest *closed* bar per market, call
engine.step(), sleep(timeframe)". Crypto and metals are different accounts with
different brokers, so each venue gets its own broker + risk manager + engine
(and its own state file), grouped here under one runner.

Kept free of ccxt / IG / network imports — those live in brokers.py and
data.py and are injected — so this wiring can be unit-tested offline with
fakes. run.py builds the real venues and hands them in.
"""
from __future__ import annotations

import time
import traceback

from .engine import Engine


class Venue:
    """One account: a broker, its risk manager, the markets it trades, and a
    `fetch(market) -> OHLCV DataFrame` callable for its data source. Owns its
    own StateStore so two venues never clobber each other's saved state."""

    def __init__(self, name, broker, risk, markets, fetch, notify=None,
                 state=None, use_closed_bar=True):
        self.name = name
        self.broker = broker
        self.risk = risk
        self.markets = markets
        self.fetch = fetch
        self.notify = notify or (lambda m: None)
        self.state = state
        self.use_closed_bar = use_closed_bar
        self.engine = Engine(broker, risk, markets, notify=self.notify)

    def restore(self):
        """Re-apply persisted kill-switch state on startup (today only)."""
        if self.state and self.state.restore_risk(self.risk):
            flag = "HALTED" if self.risk.halted else "armed"
            self.notify(f"[{self.name}] restored today's risk state ({flag})")

    def tick(self):
        """Process one round of all markets on this venue.

        A fetch/step failure on one market is logged and skipped — one bad
        market must not stop the others or kill the loop.
        """
        windows = {}
        for m in self.markets:
            try:
                df = self.fetch(m)
                # The most recent candle is usually still forming; trade on the
                # last *closed* bar to avoid acting on a repainting price.
                if self.use_closed_bar and df is not None and len(df) > 1:
                    df = df.iloc[:-1]
                if df is None or len(df) == 0:
                    continue
                windows[m["symbol"]] = df
            except Exception as e:
                self.notify(f"[{self.name}/{m['name']}] data error: {e}")

        if windows:
            # Re-arm the daily kill switch when the calendar day rolls over.
            marks = {sym: w.close.iloc[-1] for sym, w in windows.items()}
            self.risk.maybe_new_day(self.broker.equity(marks))

            for m in self.markets:
                df = windows.get(m["symbol"])
                if df is None:
                    continue
                try:
                    self.engine.step(m, df)
                except Exception as e:
                    self.notify(f"[{self.name}/{m['name']}] step error: {e}")

        self.persist()

    def persist(self):
        if not self.state:
            return
        try:
            self.state.persist(risk=self.risk, stops=self._stops())
        except Exception as e:
            self.notify(f"[{self.name}] state save failed: {e}")

    def _stops(self) -> dict:
        """Client-side stop levels to persist (paper broker tracks them)."""
        positions = getattr(self.broker, "positions", {})
        return {sym: p["stop"] for sym, p in positions.items()
                if p.get("stop") is not None}


class LiveTrader:
    """Drives the venues on a fixed cadence."""

    def __init__(self, venues, period_s, notify=None, sleep=time.sleep):
        self.venues = venues
        self.period_s = period_s
        self.notify = notify or (lambda m: None)
        self._sleep = sleep

    def tick_all(self):
        for v in self.venues:
            try:
                v.tick()
            except Exception:
                self.notify(f"[{v.name}] tick crashed:\n{traceback.format_exc()}")

    def run(self, max_cycles=None):
        """Loop forever (or `max_cycles` times, for tests/cron)."""
        for v in self.venues:
            v.restore()
        self.notify("Live trader started · venues: "
                    + ", ".join(v.name for v in self.venues))
        cycle = 0
        while max_cycles is None or cycle < max_cycles:
            self.tick_all()
            cycle += 1
            if max_cycles is not None and cycle >= max_cycles:
                break
            self._sleep(self.period_s)
