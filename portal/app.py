"""Read-only monitoring portal (FastAPI).

Runs next to the bot on the VPS and reads the same trading.db, opened in
SQLite read-only mode — the portal physically cannot change trades, positions
or settings. Only GET routes exist. Every route, the page included, needs HTTP
Basic auth (PORTAL_USER / PORTAL_PASSWORD).

Basic auth sends the password with every request, so the portal binds to
127.0.0.1 by default. Reach it from your laptop through an SSH tunnel:
    ssh -L 8080:127.0.0.1:8080 you@your-vps     then open http://localhost:8080
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from bot.database import Database

STATIC = os.path.join(os.path.dirname(__file__), "static")


def _age_seconds(ts: str | None) -> float | None:
    if not ts:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def create_app(db_path: str | None = None, user: str | None = None,
               password: str | None = None, stale_after_s: float = 180) -> FastAPI:
    db_path = db_path or os.path.join(os.getenv("TRADER_DATA_DIR", "."), "trading.db")
    user = user or os.getenv("PORTAL_USER", "admin")
    password = password or os.getenv("PORTAL_PASSWORD")
    if not password:
        raise RuntimeError("Set PORTAL_PASSWORD before starting the portal.")

    basic = HTTPBasic()

    def auth(creds: HTTPBasicCredentials = Depends(basic)) -> str:
        ok_user = secrets.compare_digest(creds.username.encode(), user.encode())
        ok_pass = secrets.compare_digest(creds.password.encode(), password.encode())
        if not (ok_user and ok_pass):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password",
                                headers={"WWW-Authenticate": "Basic"})
        return creds.username

    app = FastAPI(title="Trading Bot Portal", docs_url=None, redoc_url=None,
                  openapi_url=None, dependencies=[Depends(auth)])

    def db() -> Database | None:
        if not os.path.exists(db_path):
            return None
        return Database(db_path, readonly=True)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    @app.get("/api/status")
    def api_status(who: str = Depends(auth)):
        d = db()
        if d is None:
            return {"online": False, "state": "no-data", "mode": None, "user": who,
                    "message": "Bot has not written any data yet."}
        try:
            hb = d.last_heartbeat()
            run = d.get_kv("run", {}) or {}
            err = d.last_error()
        finally:
            d.close()
        age = _age_seconds(hb["timestamp"]) if hb else None
        online = bool(hb) and hb["status"] != "stopped" and age is not None \
            and age < max(stale_after_s, 0)
        return {
            "online": online,
            "state": hb["status"] if hb else "no-heartbeat",
            "last_heartbeat": hb["timestamp"] if hb else None,
            "seconds_since_heartbeat": round(age) if age is not None else None,
            "uptime_seconds": round(hb["uptime_seconds"]) if hb else None,
            "mode": run.get("mode"),
            "started_at": run.get("started_at"),
            "last_error": err["error_message"] if err else None,
            "last_error_at": err["timestamp"] if err else None,
            "user": who,
        }

    @app.get("/api/metrics")
    def api_metrics():
        d = db()
        if d is None:
            return {"total_equity": None, "today_pnl": None, "win_rate": None,
                    "max_drawdown": None, "trades": 0, "realized_pnl": 0, "fees": 0}
        try:
            series = d.equity_series(limit=100_000)
            stats = d.trade_stats()
        finally:
            d.close()
        values = [r["equity"] for r in series]
        today = datetime.now(timezone.utc).date().isoformat()
        todays = [r["equity"] for r in series if r["timestamp"][:10] == today]
        before = [r["equity"] for r in series if r["timestamp"][:10] < today]
        base = before[-1] if before else (todays[0] if todays else None)
        return {
            "total_equity": values[-1] if values else None,
            "today_pnl": (values[-1] - base) if values and base is not None else None,
            "win_rate": stats["win_rate"],
            "max_drawdown": _max_drawdown(values),
            "trades": stats["trades"],
            "realized_pnl": stats["realized_pnl"],
            "fees": stats["fees"],
        }

    @app.get("/api/equity")
    def api_equity(limit: int = Query(500, ge=1, le=10_000)):
        d = db()
        if d is None:
            return []
        try:
            return d.equity_series(limit=limit)
        finally:
            d.close()

    @app.get("/api/positions")
    def api_positions():
        """Every configured market with its strategy, plus the open position
        (if any) and its live P&L. Flat markets are listed too."""
        d = db()
        if d is None:
            return []
        try:
            markets = d.get_kv("markets", []) or []
            open_pos = {p["symbol"]: p for p in d.positions()}
        finally:
            d.close()
        rows, seen = [], set()
        for m in markets:
            rows.append(_row(m, open_pos.get(m["symbol"])))
            seen.add(m["symbol"])
        for sym, p in open_pos.items():           # positions for unlisted markets
            if sym not in seen:
                rows.append(_row({"venue": p["venue"], "name": p["market"],
                                  "symbol": sym, "strategy": p["strategy"]}, p))
        return rows

    @app.get("/api/trades")
    def api_trades(limit: int = Query(50, ge=1, le=1000)):
        d = db()
        if d is None:
            return []
        try:
            return d.trades(limit=limit)
        finally:
            d.close()

    return app


def _row(market: dict, pos: dict | None) -> dict:
    row = {"venue": market.get("venue"), "market": market.get("name"),
           "symbol": market.get("symbol"), "strategy": market.get("strategy"),
           "status": "open" if pos else "flat", "size": None, "entry_price": None,
           "last_price": None, "stop_loss": None, "pnl": None, "pnl_pct": None,
           "entry_time": None}
    if pos:
        last = pos["last_price"] or pos["entry_price"]
        row.update(size=pos["size"], entry_price=pos["entry_price"], last_price=last,
                   stop_loss=pos["stop_loss"], entry_time=pos["entry_time"],
                   pnl=last * pos["size"] - (pos["cost"] or pos["entry_price"] * pos["size"]),
                   pnl_pct=last / pos["entry_price"] - 1 if pos["entry_price"] else None)
    return row
