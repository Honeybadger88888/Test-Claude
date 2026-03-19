"""ML probability model for short-horizon direction prediction.

Uses a gradient boosted tree classifier with calibration when enough
historical examples are available. Falls back to shadow mode when
insufficient data exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import TimeSeriesSplit
except Exception:  # pragma: no cover - import guard for minimal environments
    HistGradientBoostingClassifier = None
    CalibratedClassifierCV = None
    TimeSeriesSplit = None


@dataclass
class MLPrediction:
    """One ML prediction output."""

    probability_up: float | None
    model_ready: bool
    mode: str
    details: dict[str, Any]


class MLProbabilityModel:
    """Trains and serves ML probabilities for P(Up)."""

    def __init__(
        self,
        min_train_samples: int = 80,
        retrain_every_rows: int = 40,
        baseline_weight: float = 0.7,
    ):
        self.min_train_samples = min_train_samples
        self.retrain_every_rows = retrain_every_rows
        self.baseline_weight = baseline_weight
        self._calibrated_model = None
        self._trained_rows = 0
        self._available = (
            HistGradientBoostingClassifier is not None
            and CalibratedClassifierCV is not None
            and TimeSeriesSplit is not None
        )
        self._last_train_info: dict[str, Any] = {"status": "not_trained"}
        self._feature_names = [
            "obi_2",
            "obi_5",
            "obi_10",
            "volatility",
            "drift",
            "market_p",
            "baseline_p",
            "time_left_sec",
            "spread",
            "mid_price",
        ]

    @property
    def is_ready(self) -> bool:
        """True when trained model can serve probabilities."""
        return self._calibrated_model is not None

    def maybe_retrain_from_depth_history(self, depth_history: list[dict[str, Any]]) -> dict[str, Any]:
        """Retrain model when enough labeled rows exist."""
        if not self._available:
            return {"trained": False, "reason": "sklearn_unavailable"}

        X, y = self._build_training_matrix(depth_history)
        n_rows = len(y)
        if n_rows < self.min_train_samples:
            return {"trained": False, "reason": "insufficient_samples", "rows": n_rows}
        if len(np.unique(y)) < 2:
            return {
                "trained": False,
                "reason": "insufficient_class_variance",
                "rows": n_rows,
            }

        if self._trained_rows and n_rows < self._trained_rows + self.retrain_every_rows:
            return {"trained": False, "reason": "retrain_threshold_not_met", "rows": n_rows}

        base_model = HistGradientBoostingClassifier(
            max_depth=4,
            learning_rate=0.05,
            max_iter=200,
            random_state=42,
        )
        n_splits = 3 if n_rows >= 120 else 2
        cv = TimeSeriesSplit(n_splits=n_splits)
        calibration_method = "isotonic"

        try:
            calibrated = CalibratedClassifierCV(
                base_model,
                method="isotonic",
                cv=cv,
            )
            calibrated.fit(X, y)
        except Exception:
            # Fallback for edge cases where isotonic split calibration cannot fit.
            calibration_method = "sigmoid"
            calibrated = CalibratedClassifierCV(
                base_model,
                method="sigmoid",
                cv=cv,
            )
            calibrated.fit(X, y)

        self._calibrated_model = calibrated
        self._trained_rows = n_rows
        self._last_train_info = {
            "status": "trained",
            "rows": n_rows,
            "calibration_method": calibration_method,
            "cv": "time_series_split",
            "n_splits": n_splits,
        }
        return {"trained": True, **self._last_train_info}

    def predict(self, features: dict[str, Any]) -> MLPrediction:
        """Predict P(Up) from current feature row."""
        if not self._available:
            return MLPrediction(
                probability_up=None,
                model_ready=False,
                mode="shadow",
                details={"reason": "sklearn_unavailable"},
            )

        row = np.array([self._feature_row(features)], dtype=float)
        if self._calibrated_model is None:
            return MLPrediction(
                probability_up=None,
                model_ready=False,
                mode="shadow",
                details={"reason": "model_not_trained"},
            )

        prob = float(self._calibrated_model.predict_proba(row)[0][1])
        return MLPrediction(
            probability_up=max(0.0, min(1.0, prob)),
            model_ready=True,
            mode="active",
            details={
                "feature_names": self._feature_names,
                "training": self._last_train_info,
            },
        )

    def blend_probability(self, baseline_p: float, ml_p: float | None) -> float:
        """Blend baseline + ML probabilities."""
        if ml_p is None or not math.isfinite(ml_p):
            return baseline_p
        w = max(0.0, min(1.0, 1.0 - self.baseline_weight))
        return max(0.0, min(1.0, baseline_p * (1 - w) + ml_p * w))

    def _build_training_matrix(self, depth_history: list[dict[str, Any]]):
        features = []
        labels = []
        for row in depth_history:
            actual = row.get("actual")
            if actual not in {"Up", "Down"}:
                continue

            vals = {
                "obi_2": row.get("obi", {}).get("2", 0.0),
                "obi_5": row.get("obi", {}).get("5", 0.0),
                "obi_10": row.get("obi", {}).get("10", 0.0),
                "volatility": row.get("volatility", 0.0),
                "drift": row.get("drift", 0.0),
                "market_p": row.get("market_p", 0.5),
                "baseline_p": row.get("baseline_p", 0.5),
                "time_left_sec": row.get("time_left_sec", 60),
                "spread": row.get("spread", 0.0),
                "mid_price": row.get("mid_price", 0.0),
            }
            features.append(self._feature_row(vals))
            labels.append(1 if actual == "Up" else 0)

        if not features:
            return np.empty((0, len(self._feature_names))), np.array([])
        return np.array(features, dtype=float), np.array(labels, dtype=int)

    def _feature_row(self, values: dict[str, Any]) -> list[float]:
        return [float(values.get(name, 0.0) or 0.0) for name in self._feature_names]
