"""Read-only portal: auth, endpoints, and that it cannot change anything."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from bot.database import Database
from portal.app import create_app

AUTH = ("admin", "s3cret")


@pytest.fixture
def seeded(tmp_path):
    path = str(tmp_path / "trading.db")
    db = Database(path)
    db.set_kv("run", {"mode": "paperlive", "started_at": "2026-01-01T00:00:00+00:00"})
    db.set_kv("markets", [
        {"venue": "paper", "name": "GOLD", "symbol": "GOLD", "strategy": "trend"},
        {"venue": "paper", "name": "OIL", "symbol": "OIL", "strategy": "meanrev"}])
    db.open_position(venue="paper", symbol="GOLD", market="GOLD", strategy="trend",
                     size=2, cost=200, entry_price=100, stop_loss=95, cash=9_800)
    db.update_marks({"GOLD": 105})
    db.open_position(venue="paper", symbol="OIL", market="OIL", strategy="meanrev",
                     size=1, cost=50, entry_price=50, cash=9_750)
    db.close_position(venue="paper", symbol="OIL", exit_price=55, reason="exit signal")
    now = datetime.now(timezone.utc)
    ts = lambda delta: (now - delta).isoformat(timespec="seconds")
    db.snapshot_equity("paper", 10_000, timestamp=ts(timedelta(days=1)))
    db.snapshot_equity("paper", 9_000, timestamp=ts(timedelta(seconds=2)))
    db.snapshot_equity("paper", 10_150, timestamp=ts(timedelta(0)))
    db.heartbeat("ok", 42)
    db.close()
    return path


@pytest.fixture
def client(seeded):
    return TestClient(create_app(seeded, *AUTH))


def test_requires_password_to_start(seeded, monkeypatch):
    monkeypatch.delenv("PORTAL_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        create_app(seeded, "admin", None)


@pytest.mark.parametrize("path", ["/", "/api/status", "/api/metrics",
                                  "/api/positions", "/api/trades", "/api/equity"])
def test_every_route_needs_auth(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, auth=("admin", "wrong")).status_code == 401
    assert client.get(path, auth=AUTH).status_code == 200


def test_status_online_with_mode(client):
    s = client.get("/api/status", auth=AUTH).json()
    assert s["online"] is True and s["mode"] == "paperlive" and s["user"] == "admin"


def test_metrics(client):
    m = client.get("/api/metrics", auth=AUTH).json()
    assert m["total_equity"] == 10_150
    assert m["today_pnl"] == pytest.approx(150)        # vs yesterday's close
    assert m["win_rate"] == 1.0 and m["trades"] == 1
    assert m["fees"] == 0
    assert m["max_drawdown"] == pytest.approx(-0.10)


def test_positions_lists_flat_and_open_markets_with_pnl(client):
    rows = {r["market"]: r for r in client.get("/api/positions", auth=AUTH).json()}
    assert rows["GOLD"]["status"] == "open"
    assert rows["GOLD"]["pnl"] == pytest.approx(105 * 2 - 200)
    assert rows["OIL"]["status"] == "flat"


def test_trades(client):
    [t] = client.get("/api/trades", auth=AUTH).json()
    assert t["market"] == "OIL" and t["pnl"] == pytest.approx(5)


def test_portal_is_read_only(client, seeded):
    for method in ("post", "put", "delete", "patch"):
        r = getattr(client, method)("/api/trades", auth=AUTH)
        assert r.status_code == 405
    before = Database(seeded, readonly=True).trades()
    client.get("/api/trades", auth=AUTH)
    assert Database(seeded, readonly=True).trades() == before


def test_offline_when_heartbeat_is_stale(seeded):
    app = create_app(seeded, *AUTH, stale_after_s=0)
    s = TestClient(app).get("/api/status", auth=AUTH).json()
    assert s["online"] is False


def test_no_database_yet(tmp_path):
    c = TestClient(create_app(str(tmp_path / "missing.db"), *AUTH))
    assert c.get("/api/status", auth=AUTH).json()["state"] == "no-data"
    assert c.get("/api/positions", auth=AUTH).json() == []
