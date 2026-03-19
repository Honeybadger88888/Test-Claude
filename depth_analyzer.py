"""Multi-depth order book imbalance analyzer.

Tracks OBI at 0-2%, 0-5%, and 0-10% depth levels side by side,
compares prediction accuracy, and finds optimal thresholds from history.
"""

import csv
import os
from datetime import datetime, timezone
from dataclasses import dataclass

import numpy as np

import config
from model import calc_order_book_imbalance


@dataclass
class DepthRecord:
    """Single window's depth analysis record."""
    timestamp: float
    obi: dict  # {depth_pct: obi_value}
    predictions: dict  # {depth_pct: "Up"/"Down"/None}
    actual_outcome: str = ""  # "Up" or "Down", filled on resolution


@dataclass
class DepthStats:
    """Running accuracy stats for a single depth level."""
    total: int = 0
    correct: int = 0

    @property
    def accuracy(self):
        return self.correct / self.total if self.total > 0 else 0.0


class DepthAnalyzer:
    """Compares OBI prediction accuracy across multiple depth levels."""

    def __init__(self):
        self.depth_levels = config.DEPTH_LEVELS  # [0.02, 0.05, 0.10]
        self.history: list[DepthRecord] = []
        self.stats: dict[float, DepthStats] = {d: DepthStats() for d in self.depth_levels}
        self.best_depth = None
        self.best_threshold = None
        self.best_selection_method = "none"
        self.best_selection_reason = "no_outcomes_yet"
        self._csv_path = os.path.join(config.TRADE_LOG_DIR, "depth_analysis.csv")
        self._csv_initialized = False

    def calc_all_obis(self, order_book, mid_price=None):
        """Compute OBI at all depth levels from a single order book snapshot.

        Args:
            order_book: dict with 'bids' and 'asks' lists of [price, qty]
            mid_price: optional override (otherwise computed from book)

        Returns:
            dict mapping depth_pct → OBI value
        """
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        return {
            depth: calc_order_book_imbalance(bids, asks, depth)
            for depth in self.depth_levels
        }

    def record_prediction(self, timestamp, obi_values):
        """Record OBI values and directional predictions for current window.

        Args:
            timestamp: window timestamp
            obi_values: dict from calc_all_obis()

        Returns:
            DepthRecord with predictions filled in
        """
        predictions = {}
        for depth, obi in obi_values.items():
            if obi > 0:
                predictions[depth] = "Up"
            elif obi < 0:
                predictions[depth] = "Down"
            else:
                predictions[depth] = None

        record = DepthRecord(
            timestamp=timestamp,
            obi=dict(obi_values),
            predictions=predictions,
        )
        self.history.append(record)
        return record

    def record_outcome(self, actual_outcome):
        """Record the actual outcome and update accuracy stats.

        Args:
            actual_outcome: "Up" or "Down"
        """
        if not self.history:
            return

        record = self.history[-1]
        record.actual_outcome = actual_outcome

        for depth in self.depth_levels:
            pred = record.predictions.get(depth)
            if pred is not None:
                self.stats[depth].total += 1
                if pred == actual_outcome:
                    self.stats[depth].correct += 1

        self._write_csv_row(record)

        self._update_best_depth()

    def get_best_obi(self, obi_values):
        """Get the OBI value from the best-performing depth level.

        Falls back to the middle depth (5%) if not enough history yet.
        """
        if self.best_depth is not None and self.best_depth in obi_values:
            return obi_values[self.best_depth]
        # Default to 5% depth
        return obi_values.get(0.05, 0.0)

    def find_optimal_thresholds(self):
        """Find the OBI threshold per depth that maximizes prediction accuracy.

        Tests at percentile extremities of historical OBI values.

        Returns:
            dict mapping depth_pct → {threshold, accuracy, sample_size}
        """
        if len(self.history) < 20:
            return {}

        results = {}
        for depth in self.depth_levels:
            obi_vals = []
            outcomes = []
            for rec in self.history:
                if rec.actual_outcome and depth in rec.obi:
                    obi_vals.append(rec.obi[depth])
                    outcomes.append(1 if rec.actual_outcome == "Up" else 0)

            if len(obi_vals) < 20:
                continue

            obi_arr = np.array(obi_vals)
            outcome_arr = np.array(outcomes)
            abs_obi = np.abs(obi_arr)

            # Test thresholds at percentile extremities
            percentiles = [50, 60, 70, 75, 80, 85, 90]
            best_acc = 0.0
            best_thresh = 0.0
            best_n = 0

            for pct in percentiles:
                thresh = np.percentile(abs_obi, pct)
                mask = abs_obi > thresh
                if mask.sum() < 5:
                    continue

                filtered_obi = obi_arr[mask]
                filtered_outcome = outcome_arr[mask]
                predictions = (filtered_obi > 0).astype(int)
                acc = np.mean(predictions == filtered_outcome)

                if acc > best_acc:
                    best_acc = acc
                    best_thresh = float(thresh)
                    best_n = int(mask.sum())

            results[depth] = {
                "threshold": best_thresh,
                "accuracy": best_acc,
                "sample_size": best_n,
            }

        return results

    def format_comparison(self):
        """Format a one-line side-by-side depth comparison string."""
        parts = []
        for depth in self.depth_levels:
            pct = int(depth * 100)
            stats = self.stats[depth]
            if self.history:
                obi = self.history[-1].obi.get(depth, 0.0)
                parts.append(
                    f"{pct}%: OBI={obi:+.3f} ({stats.accuracy:.1%} acc, n={stats.total})"
                )
            else:
                parts.append(f"{pct}%: no data")

        selected = ""
        if self.best_depth is not None:
            selected = f" | BEST={int(self.best_depth * 100)}%"
            if self.best_threshold is not None:
                selected += f" thresh={self.best_threshold:.3f}"

        return "DEPTH ANALYSIS | " + " | ".join(parts) + selected

    def get_depth_comparison(self):
        """Return structured side-by-side comparison payload."""
        latest = self.history[-1] if self.history else None
        depth_rows = []
        for depth in self.depth_levels:
            key = str(int(depth * 100))
            stats = self.stats[depth]
            depth_rows.append(
                {
                    "depth_pct": depth,
                    "depth_key": key,
                    "obi": latest.obi.get(depth, 0.0) if latest else 0.0,
                    "prediction": latest.predictions.get(depth) if latest else None,
                    "accuracy": stats.accuracy,
                    "sample_size": stats.total,
                }
            )

        return {
            "rows": depth_rows,
            "best_depth": self.best_depth,
            "best_threshold": self.best_threshold,
            "best_method": self.best_selection_method,
            "best_reason": self.best_selection_reason,
        }

    def get_history_rows(self, limit=200):
        """Get API-friendly historical OBI rows by depth."""
        rows = []
        hist = self.history[-max(1, limit):]
        for rec in hist:
            row = {
                "timestamp": self._format_timestamp(rec.timestamp),
                "raw_timestamp": rec.timestamp,
                "obi": {
                    "2": rec.obi.get(0.02, 0.0),
                    "5": rec.obi.get(0.05, 0.0),
                    "10": rec.obi.get(0.10, 0.0),
                },
                "obd": {
                    "2": rec.obi.get(0.02, 0.0),
                    "5": rec.obi.get(0.05, 0.0),
                    "10": rec.obi.get(0.10, 0.0),
                },
                "predictions": {
                    "2": rec.predictions.get(0.02),
                    "5": rec.predictions.get(0.05),
                    "10": rec.predictions.get(0.10),
                },
                "actual": rec.actual_outcome or "",
                "accuracy": {
                    "2": self.stats[0.02].accuracy,
                    "5": self.stats[0.05].accuracy,
                    "10": self.stats[0.10].accuracy,
                },
            }
            rows.append(row)
        return rows

    def load_history_from_csv(self, limit=500):
        """Warm-load history from depth_analysis.csv if present."""
        if not os.path.exists(self._csv_path):
            return []

        parsed = []
        try:
            with open(self._csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    parsed.append(
                        {
                            "timestamp": self._safe_float(row.get("timestamp", 0.0)),
                            "obi": {
                                "2": self._safe_float(row.get("obi_2pct", 0.0)),
                                "5": self._safe_float(row.get("obi_5pct", 0.0)),
                                "10": self._safe_float(row.get("obi_10pct", 0.0)),
                            },
                            "obd": {
                                "2": self._safe_float(row.get("obi_2pct", 0.0)),
                                "5": self._safe_float(row.get("obi_5pct", 0.0)),
                                "10": self._safe_float(row.get("obi_10pct", 0.0)),
                            },
                            "predictions": {
                                "2": row.get("pred_2pct") or None,
                                "5": row.get("pred_5pct") or None,
                                "10": row.get("pred_10pct") or None,
                            },
                            "actual": row.get("actual", ""),
                            "accuracy": {
                                "2": self._safe_float(row.get("acc_2pct", 0.0)),
                                "5": self._safe_float(row.get("acc_5pct", 0.0)),
                                "10": self._safe_float(row.get("acc_10pct", 0.0)),
                            },
                        }
                    )
        except (OSError, csv.Error):
            return []

        return parsed[-max(1, limit):]

    def warm_start_from_csv(self, limit=500):
        """Hydrate analyzer history/stats from persisted CSV rows."""
        rows = self.load_history_from_csv(limit=limit)
        if not rows:
            return []

        self.history.clear()
        self.stats = {d: DepthStats() for d in self.depth_levels}

        for row in rows:
            rec = DepthRecord(
                timestamp=row["timestamp"],
                obi={
                    0.02: row["obi"].get("2", 0.0),
                    0.05: row["obi"].get("5", 0.0),
                    0.10: row["obi"].get("10", 0.0),
                },
                predictions={
                    0.02: row["predictions"].get("2"),
                    0.05: row["predictions"].get("5"),
                    0.10: row["predictions"].get("10"),
                },
                actual_outcome=row.get("actual", ""),
            )
            self.history.append(rec)

            if rec.actual_outcome in {"Up", "Down"}:
                for depth in self.depth_levels:
                    pred = rec.predictions.get(depth)
                    if pred is not None:
                        self.stats[depth].total += 1
                        if pred == rec.actual_outcome:
                            self.stats[depth].correct += 1

        self._update_best_depth()
        return rows

    def _update_best_depth(self):
        """Select best depth with threshold mode or running-accuracy fallback."""
        if not self.history:
            self.best_depth = None
            self.best_threshold = None
            self.best_selection_method = "none"
            self.best_selection_reason = "no_history"
            return

        # Preferred: threshold-filtered selection once enough windows are available.
        if len(self.history) >= config.DEPTH_CALIBRATION_WINDOWS:
            results = self.find_optimal_thresholds()
            if results:
                candidates = []
                for depth, info in results.items():
                    if info["sample_size"] < 5:
                        continue
                    candidates.append(
                        {
                            "depth": depth,
                            "accuracy": info["accuracy"],
                            "sample_size": info["sample_size"],
                            "threshold": info["threshold"],
                        }
                    )
                if candidates:
                    best = sorted(
                        candidates,
                        key=lambda row: (
                            -row["accuracy"],
                            -row["sample_size"],
                            abs(row["depth"] - 0.05),
                        ),
                    )[0]
                    self.best_depth = best["depth"]
                    self.best_threshold = best["threshold"]
                    self.best_selection_method = "threshold_filtered"
                    self.best_selection_reason = (
                        f"acc={best['accuracy']:.1%}, n={best['sample_size']}, "
                        f"th={best['threshold']:.4f}"
                    )
                    return

        # Fallback: choose by running accuracy and sample size.
        running = []
        for depth in self.depth_levels:
            stats = self.stats[depth]
            if stats.total == 0:
                continue
            running.append(
                {
                    "depth": depth,
                    "accuracy": stats.accuracy,
                    "sample_size": stats.total,
                }
            )

        if running:
            best = sorted(
                running,
                key=lambda row: (
                    -row["accuracy"],
                    -row["sample_size"],
                    abs(row["depth"] - 0.05),
                ),
            )[0]
            self.best_depth = best["depth"]
            self.best_threshold = None
            self.best_selection_method = "running_accuracy"
            self.best_selection_reason = (
                f"acc={best['accuracy']:.1%}, n={best['sample_size']}"
            )
            return

        self.best_depth = None
        self.best_threshold = None
        self.best_selection_method = "none"
        self.best_selection_reason = "no_labeled_predictions"

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_timestamp(ts):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return datetime.now(timezone.utc).isoformat()

    def _write_csv_row(self, record):
        """Append a row to the depth analysis CSV."""
        os.makedirs(config.TRADE_LOG_DIR, exist_ok=True)

        write_header = not self._csv_initialized and not os.path.exists(self._csv_path)

        with open(self._csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                headers = ["timestamp"]
                for d in self.depth_levels:
                    pct = int(d * 100)
                    headers.extend([f"obi_{pct}pct", f"pred_{pct}pct"])
                headers.extend(["actual", "acc_2pct", "acc_5pct", "acc_10pct"])
                writer.writerow(headers)
                self._csv_initialized = True

            row = [record.timestamp]
            for d in self.depth_levels:
                row.append(f"{record.obi.get(d, 0):.6f}")
                row.append(record.predictions.get(d, ""))
            row.append(record.actual_outcome)
            for d in self.depth_levels:
                row.append(f"{self.stats[d].accuracy:.4f}")
            writer.writerow(row)
