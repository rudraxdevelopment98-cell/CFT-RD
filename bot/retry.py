"""Exponential backoff for flaky network calls.

Only READ calls are retried (prices, balances, positions). Order calls
(buy / close) are deliberately NOT retried: if a request timed out after the
broker accepted it, sending it again could open a second position.
"""
from __future__ import annotations

import time


def with_backoff(fn, *, attempts=4, base=1.0, cap=30.0, sleep=time.sleep,
                 on_retry=None):
    """Call fn(); on exception wait base, 2*base, 4*base... (capped) and retry.
    Re-raises the last error after `attempts` tries."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            delay = min(cap, base * 2 ** i)
            if on_retry:
                on_retry(i + 1, delay, e)
            sleep(delay)


class ResilientBroker:
    """Wraps a live broker so its read calls survive brief network blips.
    Everything else is passed straight through."""

    def __init__(self, inner, *, attempts=4, base=1.0, sleep=time.sleep,
                 notify=None):
        self.inner = inner
        self._kw = {"attempts": attempts, "base": base, "sleep": sleep}
        self._notify = notify or (lambda m: None)

    def _retry(self, name, *args):
        def on_retry(n, delay, e):
            self._notify(f"[retry] {name} failed ({e}); attempt {n + 1} in {delay:.0f}s")
        return with_backoff(lambda: getattr(self.inner, name)(*args),
                            on_retry=on_retry, **self._kw)

    def equity(self, marks):
        return self._retry("equity", marks)

    def position(self, symbol):
        return self._retry("position", symbol)

    def open_count(self):
        return self._retry("open_count")

    def buy(self, *args, **kwargs):               # never retried
        return self.inner.buy(*args, **kwargs)

    def close(self, *args, **kwargs):             # never retried
        return self.inner.close(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)
