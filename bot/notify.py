"""Notifications. Every BUY / SELL / halt should reach me on Telegram so I
can watch the bot without tailing logs on the VPS.

Falls back to console printing when no Telegram token is configured, so paper
mode and tests work with zero setup. Network/Telegram failures never crash the
trading loop — an alert that fails to send must not take a position with it.
"""
from __future__ import annotations


class Notifier:
    """Sends short text alerts. Telegram if configured, else console.

    Usage:
        notify = Notifier.from_env()        # reads TELEGRAM_* from environment
        notify("BUY BTC @ 65000")
    """

    API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 echo=print):
        self.token = token or None
        self.chat_id = chat_id or None
        self._echo = echo
        self._session = None

    @classmethod
    def from_env(cls, env=None, echo=print) -> "Notifier":
        import os
        env = env if env is not None else os.environ
        return cls(env.get("TELEGRAM_BOT_TOKEN"),
                   env.get("TELEGRAM_CHAT_ID"), echo=echo)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def __call__(self, message: str) -> None:
        # Always echo locally (logs / console), then try to push remotely.
        if self._echo:
            self._echo(f"  · {message}")
        if not self.enabled:
            return
        try:
            if self._session is None:
                import requests
                self._session = requests.Session()
            self._session.post(
                self.API.format(token=self.token),
                json={"chat_id": self.chat_id, "text": message},
                timeout=10,
            )
        except Exception as e:                       # never let alerts crash trading
            if self._echo:
                self._echo(f"  · [notify failed: {e}]")
