"""Tests for MLProbabilityModel training and prediction contracts."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_model import MLProbabilityModel


def _make_depth_history(n=120):
    rows = []
    for i in range(n):
        up = i % 2 == 0
        obi2 = 0.4 if up else -0.4
        obi5 = 0.2 if up else -0.2
        obi10 = 0.1 if up else -0.1
        rows.append(
            {
                "obi": {"2": obi2, "5": obi5, "10": obi10},
                "actual": "Up" if up else "Down",
                "volatility": 0.2 + (i % 5) * 0.01,
                "drift": 0.01 if up else -0.01,
                "market_p": 0.45 if up else 0.55,
                "baseline_p": 0.6 if up else 0.4,
                "time_left_sec": 60,
                "spread": 0.01,
                "mid_price": 70000 + i,
            }
        )
    return rows


def test_ml_training_returns_performance_and_feature_importance():
    model = MLProbabilityModel(min_train_samples=40, retrain_every_rows=1)
    result = model.maybe_retrain_from_depth_history(_make_depth_history(120))

    assert result["trained"] is True
    assert result["status"] == "trained"
    assert result["performance"]["folds"] >= 1
    assert "accuracy_mean" in result["performance"]
    assert isinstance(result["feature_importance"]["top_features"], list)


def test_ml_predict_returns_probability_when_trained():
    model = MLProbabilityModel(min_train_samples=40, retrain_every_rows=1)
    model.maybe_retrain_from_depth_history(_make_depth_history(120))

    pred = model.predict(
        {
            "obi_2": 0.3,
            "obi_5": 0.2,
            "obi_10": 0.1,
            "volatility": 0.25,
            "drift": 0.02,
            "market_p": 0.48,
            "baseline_p": 0.62,
            "time_left_sec": 55,
            "spread": 0.01,
            "mid_price": 70500,
        }
    )

    assert pred.model_ready is True
    assert pred.mode == "active"
    assert pred.probability_up is not None
    assert 0.0 <= pred.probability_up <= 1.0


def test_blend_probability_falls_back_to_baseline_on_missing_ml():
    model = MLProbabilityModel()
    assert model.blend_probability(0.61, None) == 0.61
