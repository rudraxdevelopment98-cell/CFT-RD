"""State persistence so a restart doesn't lose track.

The exchange / IG account is the source of truth for *what positions exist*,
but a few things live only in this process and MUST survive a crash or redeploy:

  * the RiskManager's daily kill-switch state (day_start_equity, halted, which
    day it is) — otherwise restarting mid-drawdown silently re-arms trading;
  * client-side stop levels per symbol — stops are tracked here, not on the
    venue, so a restart would forget them.

Stored as a single JSON file, written atomically (temp file + rename) so a
power-cut mid-write can't corrupt it.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date


class StateStore:
    def __init__(self, path: str = "state.json"):
        self.path = path

    # ---- low-level load/save ------------------------------------------- #
    def load(self) -> dict:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save(self, data: dict) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)               # atomic on POSIX & Windows
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ---- risk-manager snapshot/restore --------------------------------- #
    def snapshot_risk(self, risk) -> dict:
        return {
            "day": risk.day.isoformat() if getattr(risk, "day", None) else None,
            "day_start_equity": risk.day_start_equity,
            "halted": risk.halted,
        }

    def restore_risk(self, risk) -> bool:
        """Re-apply persisted kill-switch state to a fresh RiskManager.

        Only restores if the saved snapshot is for *today* — a new calendar
        day legitimately resets the daily limit, so stale state is ignored.
        Returns True if state was restored.
        """
        saved = self.load().get("risk")
        if not saved or saved.get("day") != date.today().isoformat():
            return False
        risk.day = date.fromisoformat(saved["day"])
        risk.day_start_equity = saved["day_start_equity"]
        risk.halted = saved["halted"]
        return True

    def persist(self, risk=None, stops: dict | None = None) -> None:
        """Write current risk + stop state to disk in one shot."""
        data = self.load()
        if risk is not None:
            data["risk"] = self.snapshot_risk(risk)
        if stops is not None:
            data["stops"] = stops
        self.save(data)
