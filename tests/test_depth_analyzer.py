"""Tests for depth analyzer side-by-side and history outputs."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from depth_analyzer import DepthAnalyzer


@pytest.fixture
def analyzer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRADE_LOG_DIR", str(tmp_path))
    return DepthAnalyzer()


def test_best_depth_uses_running_accuracy_before_calibration(analyzer):
    analyzer.record_prediction(1.0, {0.02: 0.8, 0.05: -0.4, 0.10: -0.3})
    analyzer.record_outcome("Up")

    analyzer.record_prediction(2.0, {0.02: 0.7, 0.05: -0.2, 0.10: -0.5})
    analyzer.record_outcome("Down")

    analyzer.record_prediction(3.0, {0.02: 0.6, 0.05: -0.1, 0.10: 0.2})
    analyzer.record_outcome("Down")

    comparison = analyzer.get_depth_comparison()
    assert comparison["best_depth"] == 0.05
    assert comparison["best_method"] == "running_accuracy"
    assert "acc=" in comparison["best_reason"]


def test_history_rows_include_obd_alias(analyzer):
    analyzer.record_prediction(123.0, {0.02: 0.1, 0.05: -0.2, 0.10: 0.3})
    analyzer.record_outcome("Up")

    rows = analyzer.get_history_rows(limit=5)
    assert len(rows) == 1
    assert rows[0]["obi"]["2"] == rows[0]["obd"]["2"]
    assert rows[0]["obi"]["5"] == rows[0]["obd"]["5"]
    assert rows[0]["obi"]["10"] == rows[0]["obd"]["10"]


def test_threshold_suggestions_appear_after_enough_history(analyzer):
    for i in range(30):
        direction = 1 if i % 2 == 0 else -1
        outcome = "Up" if direction == 1 else "Down"
        obi_values = {
            0.02: direction * (0.2 + (i * 0.01)),
            0.05: direction * (0.15 + (i * 0.005)),
            0.10: direction * (0.08 + (i * 0.002)),
        }
        analyzer.record_prediction(1000.0 + i, obi_values)
        analyzer.record_outcome(outcome)

    comparison = analyzer.get_depth_comparison()
    assert comparison["rows"], "Expected depth comparison rows"
    for row in comparison["rows"]:
        assert "threshold_suggestion" in row
        assert "threshold_accuracy" in row


def test_load_history_from_csv_normalizes_timestamp(analyzer):
    analyzer.record_prediction(1700000000.0, {0.02: 0.2, 0.05: 0.1, 0.10: 0.05})
    analyzer.record_outcome("Up")

    loaded = analyzer.load_history_from_csv(limit=10)
    assert loaded
    first = loaded[0]
    assert isinstance(first["timestamp"], str)
    assert first["timestamp"].endswith("+00:00")
    assert "raw_timestamp" in first
