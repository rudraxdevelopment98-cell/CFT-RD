"""Live trading orchestration.

The roadmap step: "fetch the latest *closed* bar per market, call
engine.step(), sleep(timeframe)". Crypto and metals are different accounts with
different brokers, so each venue gets its own broker + risk manager + engine,
grouped here under one runner.

With a Database (bot/database.py) the venue restores open positions, stops,
paper cash and kill-switch state from SQLite after a crash, and the runner
writes heartbeats + equity snapshots for the portal.

Kept free of ccxt / IG / network imports — those live in brokers.py and
data.py and are injected — so this wiring can be unit-tested offline with
fakes. run.py builds the real venues and hands them in.
"""
from __future__ import annotations

import time
import traceback

from .database import DbStateStore, utcnow
from .engine import Engine
from .retry import with_backoff


class Venue:
    """One account: a broker, its risk manager, the markets it trades, and a
    `fetch(market) -> OHLCV DataFrame` callable for its data source."""

    def __init__(self, name, broker, risk, markets, fetch, notify=None,
                 state=None, use_closed_bar=True, report_equity=False,
                 db=None, fetch_attempts=3, retry_sleep=time.sleep):
        self.name = name
        self.broker = broker
        self.risk = risk
        self.markets = markets
        self.fetch = fetch
        self.notify = notify or (lambda m: None)
        self.db = db
        # The database is the source of truth when given; a JSON StateStore
        # still works on its own for setups without one.
        self.state = state or (DbStateStore(db, name) if db else None)
        self.use_closed_bar = use_closed_bar
        self.report_equity = report_equity        # paper-live heartbeat
        self.fetch_attempts = fetch_attempts
        self.retry_sleep = retry_sleep
        self.engine = Engine(broker, risk, markets, notify=self.notify,
                             db=db, venue=name)

    def _is_paper(self):
        return hasattr(self.broker, "cash") and hasattr(self.broker, "positions")

    def restore(self):
        """Re-apply persisted state on startup: kill switch, stops, paper book."""
        if not self.state:
            return
        if self.state.restore_risk(self.risk):
            flag = "HALTED" if self.risk.halted else "armed"
            self.notify(f"[{self.name}] restored today's risk state ({flag})")
        saved_stops = self.state.load().get("stops") or {}
        if saved_stops:                                # re-arm stops after a restart
            self.engine.stops.update(saved_stops)
            self.notify(f"[{self.name}] restored {len(saved_stops)} stop level(s)")
        if self._is_paper() and self.state.restore_broker(self.broker):
            self.notify(f"[{self.name}] restored paper account "
                        f"(cash {self.broker.cash:,.0f}, "
                        f"{len(self.broker.positions)} open)")

    def _fetch(self, m):
        def on_retry(n, delay, e):
            self.notify(f"[{self.name}/{m['name']}] data retry {n + 1} in "
                        f"{delay:.0f}s ({e})")
        return with_backoff(lambda: self.fetch(m), attempts=self.fetch_attempts,
                            sleep=self.retry_sleep, on_retry=on_retry)

    def reconcile(self):
        """Match the database against what the broker actually holds.

        - In the DB but gone at the broker: closed outside the bot (IG's
          server-side stop, or a manual close). Recorded as a trade at the last
          known price and the stop is forgotten.
        - At the broker but not in the DB: a position the bot didn't open.
          Left alone and reported once; the strategy may still exit it.
        - Size differs by more than 1%: reported once.
        Paper venues are their own source of truth and are skipped."""
        if not self.db or self._is_paper():
            return
        warned = getattr(self, "_warned", set())
        self._warned = warned
        held = {r["symbol"]: r for r in self.db.positions(self.name)}
        for m in self.markets:
            sym = m["symbol"]
            try:
                bpos = self.broker.position(sym)
            except Exception as e:
                self.notify(f"[{self.name}/{m['name']}] reconcile skipped: {e}")
                continue
            row = held.get(sym)
            if row and not bpos:
                px = row["last_price"] or row["entry_price"]
                self.db.close_position(venue=self.name, symbol=sym, exit_price=px,
                                       reason="closed at broker (stop or manual)")
                self.engine.stops.pop(sym, None)
                self.notify(f"[{self.name}] {m['name']} was closed at the broker "
                            f"(server stop or manual); recorded at ~{px:.2f}")
            elif bpos and not row and ("untracked", sym) not in warned:
                warned.add(("untracked", sym))
                self.notify(f"[{self.name}] {m['name']}: broker holds "
                            f"{bpos['units']} that the bot did not open")
            elif bpos and row and row["size"] and \
                    abs(bpos["units"] - row["size"]) / row["size"] > 0.01 and \
                    ("size", sym) not in warned:
                warned.add(("size", sym))
                self.notify(f"[{self.name}] {m['name']}: broker size {bpos['units']} "
                            f"vs recorded {row['size']}")

    def tick(self, ts=None):
        """Process one round of all markets on this venue.

        A fetch/step failure on one market is logged and skipped — one bad
        market must not stop the others or kill the loop.
        """
        try:
            self.reconcile()
        except Exception as e:
            self.notify(f"[{self.name}] reconcile failed: {e}")
        windows = {}
        for m in self.markets:
            try:
                df = self._fetch(m)
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
                    self.engine.step(m, df, marks=marks)
                except Exception as e:
                    self.notify(f"[{self.name}/{m['name']}] step error: {e}")

            self._record(marks, ts)
            if self.report_equity and self._is_paper():
                self.notify(f"[{self.name}] equity {self.broker.equity(marks):,.0f} "
                            f"· {len(self.broker.positions)} open")

        self.persist()

    def _record(self, marks, ts):
        """Latest prices on open positions + an equity snapshot, for the portal."""
        if not self.db:
            return
        try:
            self.db.update_marks(marks)
            equity = self.broker.equity(marks)
            cash = getattr(self.broker, "cash", None)
            self.db.snapshot_equity(
                self.name, equity, cash=cash,
                unrealized_pnl=(equity - cash) - sum(
                    p.get("cost", 0) for p in self.broker.positions.values())
                if self._is_paper() else None,
                timestamp=ts)
        except Exception as e:
            self.notify(f"[{self.name}] equity snapshot failed: {e}")

    def persist(self):
        if not self.state:
            return
        try:
            broker = self.broker if self._is_paper() else None
            self.state.persist(risk=self.risk, stops=self._stops(), broker=broker)
        except Exception as e:
            self.notify(f"[{self.name}] state save failed: {e}")

    def _stops(self) -> dict:
        """Client-side stop levels to persist (the engine is the source of
        truth — works for every broker, not just the paper one)."""
        return {s: v for s, v in self.engine.stops.items() if v is not None}


class LiveTrader:
    """Drives the venues on a fixed cadence, with heartbeats for the portal."""

    def __init__(self, venues, period_s, notify=None, sleep=time.sleep,
                 db=None, mode="live", heartbeat_s=60, clock=time.monotonic):
        self.venues = venues
        self.period_s = period_s
        self.notify = notify or (lambda m: None)
        self._sleep = sleep
        self.db = db
        self.mode = mode
        self.heartbeat_s = heartbeat_s
        self._clock = clock
        self._t0 = clock()

    def _beat(self, status, error=None):
        if self.db:
            try:
                self.db.heartbeat(status, self._clock() - self._t0, error)
            except Exception:
                pass                                  # never let monitoring kill trading

    def tick_all(self):
        ts = utcnow()                                 # one timestamp per cycle
        errors = []
        for v in self.venues:
            try:
                v.tick(ts)
            except Exception as e:
                errors.append(f"{v.name}: {e}")
                self.notify(f"CRITICAL: [{v.name}] tick crashed:\n"
                            f"{traceback.format_exc()}")
        self._beat("error" if errors else "ok", "; ".join(errors) or None)

    def _wait(self):
        """Sleep one period in chunks, sending an 'idle' heartbeat each chunk so
        the portal can tell a sleeping bot from a dead one."""
        left = self.period_s
        while left > 0:
            chunk = min(self.heartbeat_s, left)
            self._sleep(chunk)
            left -= chunk
            if left > 0:
                self._beat("idle")

    def run(self, max_cycles=None):
        """Loop forever (or `max_cycles` times, for tests/cron)."""
        if self.db:
            self.db.set_kv("run", {"mode": self.mode, "started_at": utcnow(),
                                   "period_s": self.period_s})
            self.db.set_kv("markets", [
                {"venue": v.name, "name": m["name"], "symbol": m["symbol"],
                 "strategy": m["strategy"]} for v in self.venues for m in v.markets])
        for v in self.venues:
            v.restore()
        self._beat("starting")
        self.notify("Live trader started · venues: "
                    + ", ".join(v.name for v in self.venues))
        cycle = 0
        try:
            while max_cycles is None or cycle < max_cycles:
                self.tick_all()
                cycle += 1
                if max_cycles is not None and cycle >= max_cycles:
                    break
                self._wait()
        except KeyboardInterrupt:
            self.notify("Live trader stopped by user")
        except Exception as e:
            self._beat("error", f"fatal: {e}")
            self.notify(f"CRITICAL: live trader crashed and stopped: {e}")
            raise
        finally:
            self._beat("stopped")
