"""Thread-safe in-memory state for trading engine + API."""

from __future__ import annotations

import copy
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EngineState:
    """Stores latest engine snapshot and rolling histories."""

    def __init__(self, max_depth_history: int = 500, max_trade_history: int = 500):
        self._lock = threading.Lock()
        self._latest_snapshot: dict[str, Any] = self._empty_snapshot()
        self._depth_history = deque(maxlen=max_depth_history)
        self._trade_history = deque(maxlen=max_trade_history)
        self._status = {
            "running": False,
            "feed_connected": False,
            "last_error": None,
            "last_update_ts": None,
        }

    def set_running(self, running: bool):
        """Set running status."""
        with self._lock:
            self._status["running"] = running

    def set_feed_connected(self, connected: bool):
        """Set feed connectivity status."""
        with self._lock:
            self._status["feed_connected"] = connected

    def set_error(self, error: str | None):
        """Store latest error for observability."""
        with self._lock:
            self._status["last_error"] = error

    def update_snapshot(self, snapshot: dict[str, Any]):
        """Store latest snapshot and refresh status timestamps."""
        with self._lock:
            self._latest_snapshot = copy.deepcopy(snapshot)
            self._status["last_update_ts"] = snapshot.get("timestamp")
            self._status["feed_connected"] = bool(
                snapshot.get("engine", {}).get("feed_connected", False)
            )

    def add_depth_record(self, record: dict[str, Any]):
        """Append one depth history point."""
        with self._lock:
            self._depth_history.append(copy.deepcopy(record))

    def add_trade_event(self, event: dict[str, Any]):
        """Append one trade event."""
        with self._lock:
            self._trade_history.append(copy.deepcopy(event))

    def set_depth_history(self, records: list[dict[str, Any]]):
        """Replace depth history (used during warm-start)."""
        with self._lock:
            self._depth_history.clear()
            for record in records:
                self._depth_history.append(copy.deepcopy(record))

    def update_depth_outcome(self, window_ts: int, actual: str):
        """Update most recent depth row for a window with actual outcome."""
        with self._lock:
            for idx in range(len(self._depth_history) - 1, -1, -1):
                row = self._depth_history[idx]
                if row.get("window_ts") == window_ts:
                    row["actual"] = actual
                    self._depth_history[idx] = row
                    break

    def snapshot(self) -> dict[str, Any]:
        """Get latest snapshot copy."""
        with self._lock:
            snap = copy.deepcopy(self._latest_snapshot)
            snap["status"] = copy.deepcopy(self._status)
            return snap

    def depth_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent depth history rows."""
        with self._lock:
            rows = list(self._depth_history)[-max(limit, 1):]
            return copy.deepcopy(rows)

    def trade_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent trade events."""
        with self._lock:
            rows = list(self._trade_history)[-max(limit, 1):]
            return copy.deepcopy(rows)

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "timestamp": now_iso,
            "engine": {"state": "initializing", "feed_connected": False},
            "window": {},
            "market": {},
            "price_feed": {},
            "depth": {},
            "model": {},
            "ml": {"mode": "shadow", "state": "warming"},
            "signal": {},
            "risk": {},
            "stats": {},
            "trades": {"recent": []},
            "errors": [],
        }
