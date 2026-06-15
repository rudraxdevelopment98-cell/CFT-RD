"""Alerts must reach me, but a failed alert must never crash trading."""
from bot.notify import Notifier


def test_echoes_locally_and_is_disabled_without_creds():
    seen = []
    n = Notifier(echo=seen.append)
    assert n.enabled is False
    n("BUY BTC @ 100")
    assert seen == ["  · BUY BTC @ 100"]


def test_from_env_reads_telegram_keys():
    n = Notifier.from_env(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"},
                          echo=lambda m: None)
    assert n.enabled is True


def test_send_failure_is_swallowed(monkeypatch):
    seen = []
    n = Notifier(token="t", chat_id="c", echo=seen.append)

    class BoomSession:
        def post(self, *a, **k):
            raise RuntimeError("network down")

    n._session = BoomSession()
    n("BUY BTC @ 100")                              # must not raise
    assert any("notify failed" in m for m in seen)
