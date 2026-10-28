"""Logging setup for running as a 24/7 service.

A detached service can't rely on `print` — output needs to land in a rotating
file you can tail on the VPS/Pi, while still showing on the console when run by
hand. `Notifier` routes its echo through this logger, so every BUY/SELL/halt is
both pushed to Telegram and written to the log.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(data_dir: str = ".", level=logging.INFO) -> logging.Logger:
    log = logging.getLogger("trader")
    if log.handlers:                                  # idempotent
        return log
    log.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            "%Y-%m-%d %H:%M:%S")

    os.makedirs(data_dir, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(data_dir, "trader.log"),
                             maxBytes=2_000_000, backupCount=5)
    fh.setFormatter(fmt)
    log.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(ch)
    return log
