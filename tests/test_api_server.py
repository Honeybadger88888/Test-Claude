"""Tests for FastAPI endpoints serving engine state."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from api_server import create_app
from engine_state import EngineState


def _seed_state():
    state = EngineState()
    state.set_running(True)
    state.set_feed_connected(True)
    state.update_snapshot(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engine": {"state": "running", "feed_connected": True},
            "window": {"window_ts": 123, "seconds_left": 45},
            "market": {"slug": "btc-updown-5m-123", "up_price": 0.55},
            "price_feed": {"price": 50000},
            "depth": {
                "rows": [
                    {"depth_pct": 0.02, "obi": 0.1, "accuracy": 0.6, "sample_size": 50},
                    {"depth_pct": 0.05, "obi": 0.2, "accuracy": 0.7, "sample_size": 50},
                    {"depth_pct": 0.10, "obi": 0.3, "accuracy": 0.8, "sample_size": 50},
                ],
                "best_depth": 0.10,
            },
            "model": {"baseline_probability_up": 0.6},
            "ml": {"mode": "shadow", "ready": False},
            "signal": {"should_trade": True, "direction": "Up", "edge": 0.05},
            "risk": {"can_trade": True, "reason": "OK"},
            "stats": {"total_trades": 1},
            "trades": {"recent": []},
            "errors": [],
        }
    )
    state.add_depth_record({"window_ts": 123, "obi": {"2": 0.1, "5": 0.2, "10": 0.3}, "actual": "Up"})
    state.add_trade_event({"trade_id": 1, "status": "OPEN"})
    state.add_trade_event(
        {
            "trade_id": 1,
            "status": "RESOLVED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": "Win",
            "pnl": 120.5,
            "bankroll_after": 10120.5,
        }
    )
    return state


def test_health_endpoint():
    app = create_app(state=_seed_state(), start_engine_on_startup=False)
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "running" in body
    assert "last_update_ts" in body


def test_snapshot_endpoint_shape():
    app = create_app(state=_seed_state(), start_engine_on_startup=False)
    client = TestClient(app)

    resp = client.get("/api/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert "window" in data
    assert "market" in data
    assert "depth" in data
    assert "signal" in data
    assert "status" in data


def test_depth_history_endpoint_returns_rows():
    app = create_app(state=_seed_state(), start_engine_on_startup=False)
    client = TestClient(app)

    resp = client.get("/api/history/depth?limit=5")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["obi"]["5"] == 0.2


def test_performance_history_endpoint_returns_curve_points():
    app = create_app(state=_seed_state(), start_engine_on_startup=False)
    client = TestClient(app)

    resp = client.get("/api/history/performance?limit=10")
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["cumulative_pnl"] == 120.5
    assert rows[0]["win_rate"] == 1.0
