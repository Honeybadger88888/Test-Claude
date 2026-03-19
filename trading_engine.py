"""Continuous auto-paper-trading engine with snapshot publishing."""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import config
from depth_analyzer import DepthAnalyzer, DepthRecord
from edge import calc_edge, calc_position_size, should_trade
from engine_state import EngineState
from logger import TradeLogger
from ml_model import MLPrediction, MLProbabilityModel
from model import calc_short_term_drift, calc_up_probability, estimate_volatility
from paper_trader import PaperTrader, Trade
from polymarket import PolymarketClient
from price_feed import PriceFeed


class TradingEngine:
    """Runs the strategy loop and publishes live state for UI/API consumers."""

    def __init__(
        self,
        state: EngineState | None = None,
        *,
        auto_trade: bool = True,
        poll_interval_sec: float = 1.0,
        price_feed: PriceFeed | None = None,
        polymarket_client: PolymarketClient | None = None,
        depth_analyzer: DepthAnalyzer | None = None,
        paper_trader: PaperTrader | None = None,
        trade_logger: TradeLogger | None = None,
        ml_model: MLProbabilityModel | None = None,
    ):
        self.state = state or EngineState()
        self.auto_trade = auto_trade
        self.poll_interval_sec = max(0.2, poll_interval_sec)

        self.feed = price_feed or PriceFeed()
        self.poly = polymarket_client or PolymarketClient()
        self.analyzer = depth_analyzer or DepthAnalyzer()
        self.trader = paper_trader or PaperTrader()
        self.log = trade_logger or TradeLogger()
        self.ml_model = ml_model or MLProbabilityModel()

        self._running = False
        self._thread = None

        self._window_ts: int | None = None
        self._window_slug = ""
        self._window_open_price: float | None = None
        self._window_prediction_recorded = False
        self._pending_trade: Trade | None = None
        self._pending_trade_window_ts: int | None = None
        self._last_price: float | None = None
        self._last_snapshot: dict[str, Any] | None = None

        self._cached_market = None
        self._cached_market_window_ts = None
        self._cached_market_p = 0.5
        self._cached_market_p_ts = 0.0
        self._lock = threading.Lock()

        warm_history = self.analyzer.warm_start_from_csv(limit=500)
        if warm_history:
            self.state.set_depth_history(warm_history)

    def start(self):
        """Start feed and engine loop thread."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self.feed.start()
        connected = self.feed.wait_for_connection(timeout=30)
        self.state.set_feed_connected(bool(connected))
        self.state.set_running(True)

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop loop and underlying feed."""
        with self._lock:
            self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.feed.stop()
        self.state.set_running(False)

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def run_tick(self):
        """Run one engine step (public for tests)."""
        now = time.time()
        current_price = self.feed.get_current_price()
        if current_price is not None:
            self._last_price = current_price
        else:
            current_price = self._last_price

        feed_connected = self.feed.wait_for_connection(timeout=0)

        window_ts = self.poly.get_current_window_ts()
        seconds_left = self.poly.get_seconds_until_close()
        if self._window_ts is None:
            self._window_ts = window_ts
            self._window_slug = f"btc-updown-5m-{window_ts}"
            self._window_open_price = current_price
        elif window_ts != self._window_ts:
            self._close_previous_window(current_price)
            self._window_ts = window_ts
            self._window_slug = f"btc-updown-5m-{window_ts}"
            self._window_open_price = current_price
            self._window_prediction_recorded = False

        market = self._get_market(window_ts)
        market_p = self._get_market_probability(market, now)

        order_book = self.feed.get_order_book()
        obi_values = self.analyzer.calc_all_obis(order_book)
        spread, mid_price = self._calc_book_metrics(order_book)

        candles = self.feed.get_recent_candles()
        volatility = estimate_volatility(candles)
        drift = calc_short_term_drift(candles)
        best_obi = self.analyzer.get_best_obi(obi_values)

        if current_price is not None and self._window_open_price is not None:
            baseline_p = calc_up_probability(
                current_price=current_price,
                window_open=self._window_open_price,
                time_left_sec=max(0, seconds_left),
                volatility=volatility,
                obi_signal=best_obi,
                drift=drift,
            )
        else:
            baseline_p = 0.5

        ml_features = {
            "obi_2": obi_values.get(0.02, 0.0),
            "obi_5": obi_values.get(0.05, 0.0),
            "obi_10": obi_values.get(0.10, 0.0),
            "volatility": volatility,
            "drift": drift,
            "market_p": market_p,
            "baseline_p": baseline_p,
            "time_left_sec": seconds_left,
            "spread": spread,
            "mid_price": mid_price,
        }
        ml_pred = self.ml_model.predict(ml_features)
        final_p, ml_decision = self._select_probability_for_trading(
            baseline_p=baseline_p,
            market_p=market_p,
            ml_prediction=ml_pred,
        )

        edge_val = calc_edge(final_p, market_p)
        should_open, direction, _ = should_trade(final_p, market_p)
        can_trade, risk_reason = self.trader.check_risk_limits()
        position_size = (
            calc_position_size(final_p, market_p, self.trader.bankroll)
            if should_open
            else 0.0
        )

        training_status = None
        if (
            not self._window_prediction_recorded
            and 5 < seconds_left <= config.DECISION_SECS_BEFORE_CLOSE
        ):
            record = self.analyzer.record_prediction(now, obi_values)
            self._window_prediction_recorded = True
            self.state.add_depth_record(
                self._depth_record_to_history_row(
                    record=record,
                    window_ts=self._window_ts,
                    baseline_p=baseline_p,
                    market_p=market_p,
                    volatility=volatility,
                    drift=drift,
                    spread=spread,
                    mid_price=mid_price,
                    time_left_sec=seconds_left,
                )
            )

            training_status = self.ml_model.maybe_retrain_from_depth_history(
                self.state.depth_history(limit=500)
            )

        if (
            self.auto_trade
            and self._window_prediction_recorded
            and self._pending_trade is None
            and 5 < seconds_left <= config.DECISION_SECS_BEFORE_CLOSE
        ):
            if should_open and can_trade and position_size >= 1.0:
                market_slug = market.get("slug", self._window_slug) if market else self._window_slug
                trade = self.trader.open_trade(
                    direction=direction,
                    size=position_size,
                    market_p=market_p,
                    my_p=final_p,
                    edge=edge_val,
                    window_slug=market_slug,
                    entry_price=current_price or 0.0,
                )
                self._pending_trade = trade
                self._pending_trade_window_ts = self._window_ts
                self.state.add_trade_event(self._trade_to_event(trade, status="OPEN"))
            elif should_open and position_size < 1.0:
                risk_reason = "position_too_small"

        depth_comparison = self.analyzer.get_depth_comparison()
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engine": {
                "state": "running" if self.is_running() else "stopped",
                "auto_trade": self.auto_trade,
                "feed_connected": bool(feed_connected),
                "pending_trade": bool(self._pending_trade),
            },
            "window": {
                "window_ts": self._window_ts,
                "window_slug": self._window_slug,
                "seconds_left": seconds_left,
                "open_price": self._window_open_price,
                "current_price": current_price,
            },
            "market": {
                "slug": market.get("slug") if market else None,
                "question": market.get("question") if market else None,
                "up_token_id": market.get("up_token_id") if market else None,
                "down_token_id": market.get("down_token_id") if market else None,
                "up_price": market_p,
                "down_price": max(0.0, min(1.0, 1.0 - market_p)),
            },
            "price_feed": {
                "price": current_price,
                "spread": spread,
                "mid_price": mid_price,
                "top_bids": order_book.get("bids", [])[:5],
                "top_asks": order_book.get("asks", [])[:5],
                "candles_count": len(candles),
            },
            "depth": depth_comparison,
            "model": {
                "volatility": volatility,
                "drift": drift,
                "best_obi": best_obi,
                "baseline_probability_up": baseline_p,
            },
            "ml": {
                "mode": ml_pred.mode,
                "ready": ml_pred.model_ready,
                "probability_up": ml_pred.probability_up,
                "blended_probability_up": final_p,
                "trade_control_mode": ml_decision["trade_control_mode"],
                "decision_source": ml_decision["decision_source"],
                "consensus": ml_decision.get("consensus"),
                "details": ml_pred.details,
                "training": training_status,
            },
            "signal": {
                "direction": direction,
                "should_trade": should_open,
                "edge": edge_val,
                "position_size": position_size,
            },
            "risk": {
                "can_trade": can_trade,
                "reason": risk_reason,
                "bankroll": self.trader.bankroll,
            },
            "stats": self.trader.get_session_stats(),
            "trades": {
                "recent": self.state.trade_history(limit=20),
            },
            "errors": [],
        }
        self._last_snapshot = snapshot
        self.state.update_snapshot(snapshot)

    def _run_loop(self):
        while self.is_running():
            start = time.time()
            try:
                self.run_tick()
                self.state.set_error(None)
            except Exception as exc:  # pragma: no cover - resilience path
                self.state.set_error(str(exc))
                traceback.print_exc()

            elapsed = time.time() - start
            sleep_for = max(0.0, self.poll_interval_sec - elapsed)
            time.sleep(sleep_for)

    def _close_previous_window(self, latest_price: float | None):
        if not self._window_prediction_recorded:
            self._pending_trade = None
            self._pending_trade_window_ts = None
            return

        exit_price = latest_price or self._last_price or self._window_open_price or 0.0
        open_price = self._window_open_price or exit_price
        actual_outcome = "Up" if exit_price >= open_price else "Down"

        self.analyzer.record_outcome(actual_outcome)
        if self._window_ts is not None:
            self.state.update_depth_outcome(self._window_ts, actual_outcome)

        if (
            self._pending_trade is not None
            and self._pending_trade_window_ts == self._window_ts
        ):
            resolved = self.trader.resolve_trade(
                self._pending_trade,
                actual_outcome=actual_outcome,
                exit_price=exit_price,
            )
            self.state.add_trade_event(self._trade_to_event(resolved, status="RESOLVED"))
            self.log.log_trade(resolved)
            self._pending_trade = None
            self._pending_trade_window_ts = None

    def _get_market(self, window_ts: int):
        if self._cached_market_window_ts != window_ts:
            self._cached_market = self.poly.get_current_market()
            self._cached_market_window_ts = window_ts
        return self._cached_market

    def _get_market_probability(self, market, now_ts: float):
        if market is None:
            return self._cached_market_p

        if now_ts - self._cached_market_p_ts < 2:
            return self._cached_market_p

        token = market.get("up_token_id")
        price = self.poly.get_market_price(token) if token else None
        if price is not None and 0 < price < 1:
            self._cached_market_p = price
        self._cached_market_p_ts = now_ts
        return self._cached_market_p

    @staticmethod
    def _calc_book_metrics(order_book: dict[str, Any]):
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])
        if not bids or not asks:
            return 0.0, 0.0

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread = max(0.0, best_ask - best_bid)
        mid = (best_ask + best_bid) / 2
        return spread, mid

    def _depth_record_to_history_row(
        self,
        record: DepthRecord,
        window_ts: int | None,
        baseline_p: float,
        market_p: float,
        volatility: float,
        drift: float,
        spread: float,
        mid_price: float,
        time_left_sec: int,
    ):
        return {
            "timestamp": datetime.fromtimestamp(record.timestamp, tz=timezone.utc).isoformat(),
            "window_ts": window_ts,
            "obi": {
                "2": record.obi.get(0.02, 0.0),
                "5": record.obi.get(0.05, 0.0),
                "10": record.obi.get(0.10, 0.0),
            },
            "obd": {
                "2": record.obi.get(0.02, 0.0),
                "5": record.obi.get(0.05, 0.0),
                "10": record.obi.get(0.10, 0.0),
            },
            "predictions": {
                "2": record.predictions.get(0.02),
                "5": record.predictions.get(0.05),
                "10": record.predictions.get(0.10),
            },
            "actual": "",
            "volatility": volatility,
            "drift": drift,
            "market_p": market_p,
            "baseline_p": baseline_p,
            "time_left_sec": time_left_sec,
            "spread": spread,
            "mid_price": mid_price,
        }

    @staticmethod
    def _trade_to_event(trade: Trade, status: str):
        return {
            "status": status,
            "trade_id": trade.trade_id,
            "timestamp": datetime.fromtimestamp(trade.timestamp, tz=timezone.utc).isoformat(),
            "direction": trade.direction,
            "size": trade.size,
            "market_p": trade.market_p,
            "my_p": trade.my_p,
            "edge": trade.edge,
            "window_slug": trade.window_slug,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "result": trade.result,
            "pnl": trade.pnl,
            "bankroll_after": trade.bankroll_after,
        }

    def _select_probability_for_trading(
        self,
        baseline_p: float,
        market_p: float,
        ml_prediction: MLPrediction,
    ):
        """Choose effective trade probability using configured ML mode."""
        mode = (config.ML_TRADE_CONTROL_MODE or "blended").lower()
        ml_p = ml_prediction.probability_up

        if mode == "baseline" or ml_p is None or not ml_prediction.model_ready:
            return baseline_p, {
                "trade_control_mode": mode,
                "decision_source": "baseline",
            }

        if mode == "ml_only":
            return ml_p, {
                "trade_control_mode": mode,
                "decision_source": "ml_only",
            }

        if mode == "consensus":
            baseline_trade, baseline_dir, _ = should_trade(baseline_p, market_p)
            ml_trade, ml_dir, _ = should_trade(ml_p, market_p)
            agreed = baseline_trade and ml_trade and baseline_dir == ml_dir
            if agreed:
                final_p = self.ml_model.blend_probability(baseline_p=baseline_p, ml_p=ml_p)
                return final_p, {
                    "trade_control_mode": mode,
                    "decision_source": "consensus_blend",
                    "consensus": {
                        "agreed": True,
                        "baseline_direction": baseline_dir,
                        "ml_direction": ml_dir,
                    },
                }
            return market_p, {
                "trade_control_mode": mode,
                "decision_source": "consensus_blocked",
                "consensus": {
                    "agreed": False,
                    "baseline_direction": baseline_dir if baseline_trade else "None",
                    "ml_direction": ml_dir if ml_trade else "None",
                },
            }

        # default: blended
        final_p = self.ml_model.blend_probability(baseline_p=baseline_p, ml_p=ml_p)
        return final_p, {
            "trade_control_mode": "blended",
            "decision_source": "blended",
        }
