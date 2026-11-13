"""SQLite persistence — the single source of truth for trades, open positions,
heartbeats and equity history.

Every state change that moves money (opening or closing a position, plus the
paper account's cash) is written in ONE transaction, so a crash can never leave
the database half-updated: either the whole change landed or none of it did.

The bot writes; the portal opens the same file read-only (`readonly=True`).
WAL mode lets the portal read while the bot writes.

Tables (the four asked for, plus a small key/value table):
    trades            one row per closed round trip
    positions         currently open positions (deleted on close)
    heartbeats        "I'm alive" pings + errors, for the portal's health badge
    equity_snapshots  account value per venue per cycle (equity curve)
    kv                small JSON settings: risk state, paper cash, run mode
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT, market TEXT, symbol TEXT, strategy TEXT, side TEXT,
    size REAL, entry_time TEXT, exit_time TEXT,
    entry_price REAL, exit_price REAL,
    pnl REAL, pnl_pct REAL, commission REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS positions(
    symbol TEXT PRIMARY KEY,
    venue TEXT, market TEXT, strategy TEXT, side TEXT,
    size REAL, cost REAL, entry_price REAL,
    stop_loss REAL, take_profit REAL, last_price REAL,
    entry_time TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS heartbeats(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT, status TEXT, uptime_seconds REAL, error_message TEXT);
CREATE TABLE IF NOT EXISTS equity_snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT, venue TEXT, total_equity REAL, cash REAL, unrealized_pnl REAL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_trades_exit ON trades(exit_time);
CREATE INDEX IF NOT EXISTS ix_equity_ts ON equity_snapshots(timestamp);
"""

HEARTBEAT_KEEP = 5_000            # older heartbeat rows are pruned


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        if readonly:
            self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                        check_same_thread=False)
        else:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def close(self):
        self.conn.close()

    # ---- plumbing ------------------------------------------------------ #
    @contextmanager
    def tx(self):
        """All-or-nothing write block. Rolls back on any exception."""
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _rows(self, sql, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _one(self, sql, args=()) -> dict | None:
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    # ---- key/value ----------------------------------------------------- #
    def set_kv(self, key, value):
        with self.tx() as c:
            self._set_kv(c, key, value)

    @staticmethod
    def _set_kv(c, key, value):
        c.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)",
                  (key, json.dumps(value, default=float)))

    def get_kv(self, key, default=None):
        row = self._one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    # ---- positions & trades (the money path) --------------------------- #
    def open_position(self, *, venue, symbol, market, strategy, size, cost,
                      entry_price, stop_loss=None, take_profit=None,
                      side="long", cash=None):
        """Record a new open position (and the paper cash it consumed) atomically."""
        now = utcnow()
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO positions(symbol, venue, market, strategy,"
                " side, size, cost, entry_price, stop_loss, take_profit, last_price,"
                " entry_time, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, venue, market, strategy, side, float(size), float(cost),
                 float(entry_price), _f(stop_loss), _f(take_profit),
                 float(entry_price), now, now))
            if cash is not None:
                self._set_kv(c, f"{venue}.cash", float(cash))

    def close_position(self, *, venue, symbol, exit_price, reason, pnl=None,
                       pnl_pct=None, commission=None, cash=None,
                       market=None, strategy=None) -> int:
        """Move an open position into the trades table atomically.

        pnl / pnl_pct are computed from the stored entry when the broker
        doesn't report them (live adapters). Returns the new trade id."""
        now = utcnow()
        with self.tx() as c:
            pos = c.execute("SELECT * FROM positions WHERE symbol=?",
                            (symbol,)).fetchone()
            pos = dict(pos) if pos else {}
            entry = pos.get("entry_price")
            size = pos.get("size")
            if pnl is None and entry and size:
                pnl = (float(exit_price) - entry) * size
            if pnl_pct is None and entry:
                pnl_pct = float(exit_price) / entry - 1
            cur = c.execute(
                "INSERT INTO trades(venue, market, symbol, strategy, side, size,"
                " entry_time, exit_time, entry_price, exit_price, pnl, pnl_pct,"
                " commission, reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (venue, pos.get("market", market or symbol), symbol,
                 pos.get("strategy", strategy), pos.get("side", "long"), size,
                 pos.get("entry_time"), now, entry, float(exit_price),
                 _f(pnl), _f(pnl_pct), _f(commission), reason))
            c.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            if cash is not None:
                self._set_kv(c, f"{venue}.cash", float(cash))
            return cur.lastrowid

    def update_marks(self, marks: dict):
        now = utcnow()
        with self.tx() as c:
            c.executemany(
                "UPDATE positions SET last_price=?, updated_at=? WHERE symbol=?",
                [(float(p), now, s) for s, p in marks.items()])

    def positions(self, venue=None) -> list[dict]:
        if venue:
            return self._rows("SELECT * FROM positions WHERE venue=? "
                              "ORDER BY entry_time", (venue,))
        return self._rows("SELECT * FROM positions ORDER BY entry_time")

    def trades(self, limit=50, venue=None) -> list[dict]:
        if venue:
            return self._rows("SELECT * FROM trades WHERE venue=? "
                              "ORDER BY id DESC LIMIT ?", (venue, limit))
        return self._rows("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    def trade_stats(self) -> dict:
        r = self._one(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,"
            " COALESCE(SUM(pnl), 0) AS realized,"
            " COALESCE(SUM(commission), 0) AS fees FROM trades")
        n = r["n"] or 0
        return {"trades": n, "wins": r["wins"] or 0,
                "win_rate": (r["wins"] or 0) / n if n else None,
                "realized_pnl": r["realized"], "fees": r["fees"]}

    # ---- heartbeats ---------------------------------------------------- #
    def heartbeat(self, status, uptime_seconds=0.0, error_message=None):
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO heartbeats(timestamp, status, uptime_seconds,"
                " error_message) VALUES(?,?,?,?)",
                (utcnow(), status, float(uptime_seconds), error_message))
            if cur.lastrowid % 500 == 0:
                c.execute("DELETE FROM heartbeats WHERE id <= ?",
                          (cur.lastrowid - HEARTBEAT_KEEP,))

    def last_heartbeat(self) -> dict | None:
        return self._one("SELECT * FROM heartbeats ORDER BY id DESC LIMIT 1")

    def last_error(self) -> dict | None:
        return self._one("SELECT * FROM heartbeats WHERE error_message IS NOT NULL"
                         " ORDER BY id DESC LIMIT 1")

    # ---- equity -------------------------------------------------------- #
    def snapshot_equity(self, venue, total_equity, cash=None,
                        unrealized_pnl=None, timestamp=None):
        with self.tx() as c:
            c.execute(
                "INSERT INTO equity_snapshots(timestamp, venue, total_equity, cash,"
                " unrealized_pnl) VALUES(?,?,?,?,?)",
                (timestamp or utcnow(), venue, float(total_equity), _f(cash),
                 _f(unrealized_pnl)))

    def equity_series(self, limit=2000) -> list[dict]:
        """Account value over time, summed across venues per cycle timestamp."""
        # one row per (cycle, venue): the latest, so a repeated snapshot in the
        # same second can't double-count a venue
        rows = self._rows(
            "SELECT timestamp, SUM(total_equity) AS equity FROM equity_snapshots"
            " WHERE id IN (SELECT MAX(id) FROM equity_snapshots"
            "              GROUP BY timestamp, venue)"
            " GROUP BY timestamp ORDER BY timestamp DESC LIMIT ?", (limit,))
        return rows[::-1]


def _f(x):
    return None if x is None else float(x)


class DbStateStore:
    """Drop-in for the JSON StateStore, backed by the Database, for one venue.

    Positions themselves are written by the Engine as they open/close; this
    adapter persists the rest (kill-switch state, stops, paper cash) and rebuilds
    a paper broker's book from the positions table after a restart."""

    def __init__(self, db: Database, venue: str):
        self.db = db
        self.venue = venue

    def persist(self, risk=None, stops: dict | None = None, broker=None):
        if risk is not None:
            self.db.set_kv(f"{self.venue}.risk", {
                "day": risk.day.isoformat() if getattr(risk, "day", None) else None,
                "day_start_equity": risk.day_start_equity,
                "halted": risk.halted})
        if stops:
            with self.db.tx() as c:
                c.executemany("UPDATE positions SET stop_loss=? WHERE symbol=?",
                              [(float(v), s) for s, v in stops.items()])
        if broker is not None and hasattr(broker, "cash"):
            self.db.set_kv(f"{self.venue}.cash", float(broker.cash))

    def restore_risk(self, risk) -> bool:
        saved = self.db.get_kv(f"{self.venue}.risk")
        if not saved or saved.get("day") != date.today().isoformat():
            return False
        risk.day = date.fromisoformat(saved["day"])
        risk.day_start_equity = saved["day_start_equity"]
        risk.halted = saved["halted"]
        return True

    def restore_broker(self, broker) -> bool:
        cash = self.db.get_kv(f"{self.venue}.cash")
        rows = self.db.positions(self.venue)
        if cash is None and not rows:
            return False
        if cash is not None:
            broker.cash = cash
        broker.positions = {
            r["symbol"]: {"units": r["size"], "entry": r["entry_price"],
                          "cost": r["cost"], "stop": r["stop_loss"]}
            for r in rows}
        return True

    def load(self) -> dict:
        return {"stops": {r["symbol"]: r["stop_loss"]
                          for r in self.db.positions(self.venue)
                          if r["stop_loss"] is not None}}
