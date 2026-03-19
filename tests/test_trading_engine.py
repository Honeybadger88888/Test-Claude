"""Tests for TradingEngine auto-trade behavior."""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from depth_analyzer import DepthAnalyzer
from engine_state import EngineState
from paper_trader import PaperTrader
from trading_engine import TradingEngine


class FakeFeed:
    def __init__(self):
        self.price = 50000.0
        self.connected = True
        self.book = {
            "bids": [[50000.0, 12.0], [49999.0, 20.0]],
            "asks": [[50001.0, 10.0], [50002.0, 18.0]],
        }
        self.candles = [
            {"open": 49900, "high": 50100, "low": 49800, "close": 50000 + i, "volume": 100, "timestamp": i}
            for i in range(30)
        ]

    def start(self):
        return None

    def stop(self):
        return None

    def wait_for_connection(self, timeout=30):
        return self.connected

    def get_current_price(self):
        return self.price

    def get_order_book(self):
        return self.book

    def get_recent_candles(self, n=None):
        return self.candles if n is None else self.candles[-n:]


class FakePolymarket:
    def __init__(self):
        self.window_ts = 1000
        self.seconds_left = config.DECISION_SECS_BEFORE_CLOSE
        self.price = 0.40
        self.market = {
            "slug": f"btc-updown-5m-{self.window_ts}",
            "question": "BTC up/down?",
            "up_token_id": "up-token",
            "down_token_id": "down-token",
        }

    def get_current_window_ts(self):
        return self.window_ts

    def get_seconds_until_close(self):
        return self.seconds_left

    def get_current_market(self):
        self.market["slug"] = f"btc-updown-5m-{self.window_ts}"
        return self.market

    def get_market_price(self, token_id, side="buy"):
        return self.price


class StubMLModel:
    def __init__(self, probability_up=None, ready=False):
        self._probability_up = probability_up
        self._ready = ready

    def predict(self, features):
        return SimpleNamespace(
            probability_up=self._probability_up,
            model_ready=self._ready,
            mode="active" if self._ready else "shadow",
            details={},
        )

    def blend_probability(self, baseline_p, ml_p):
        if ml_p is None:
            return baseline_p
        return (baseline_p + ml_p) / 2

    def maybe_retrain_from_depth_history(self, depth_history):
        return {"trained": False}


def _make_engine(poly=None, trader=None, ml_model=None):
    state = EngineState(max_depth_history=50, max_trade_history=50)
    feed = FakeFeed()
    engine = TradingEngine(
        state=state,
        auto_trade=True,
        poll_interval_sec=0.1,
        price_feed=feed,
        polymarket_client=poly or FakePolymarket(),
        depth_analyzer=DepthAnalyzer(),
        paper_trader=trader or PaperTrader(),
        ml_model=ml_model or StubMLModel(),
    )
    return engine, state, feed


def test_auto_trade_opens_when_signal_and_risk_pass(monkeypatch):
    engine, state, _ = _make_engine()
    monkeypatch.setattr("trading_engine.calc_up_probability", lambda **_: 0.85)

    engine.run_tick()

    trades = state.trade_history(limit=10)
    assert trades, "Expected an OPEN trade event"
    assert trades[-1]["status"] == "OPEN"
    assert trades[-1]["direction"] == "Up"


def test_no_trade_when_risk_limit_blocks(monkeypatch):
    trader = PaperTrader(bankroll=10000)
    trader.consecutive_losses = config.MAX_CONSECUTIVE_LOSSES
    engine, state, _ = _make_engine(trader=trader)
    monkeypatch.setattr("trading_engine.calc_up_probability", lambda **_: 0.85)

    engine.run_tick()

    trades = state.trade_history(limit=10)
    assert trades == []


def test_trade_resolves_on_window_rollover(monkeypatch):
    poly = FakePolymarket()
    engine, state, feed = _make_engine(poly=poly)
    monkeypatch.setattr("trading_engine.calc_up_probability", lambda **_: 0.90)

    engine.run_tick()  # open trade at decision point
    assert state.trade_history(limit=10)[-1]["status"] == "OPEN"

    # Move to next window and close previous trade as a win
    feed.price = 50050.0
    poly.window_ts += 300
    poly.seconds_left = 299
    engine.run_tick()

    trades = state.trade_history(limit=10)
    assert any(t["status"] == "RESOLVED" for t in trades)


def test_consensus_mode_blocks_when_models_disagree(monkeypatch):
    monkeypatch.setattr(config, "ML_TRADE_CONTROL_MODE", "consensus")
    ml = StubMLModel(probability_up=0.10, ready=True)  # strong Down
    engine, _, _ = _make_engine(ml_model=ml)
    monkeypatch.setattr("trading_engine.calc_up_probability", lambda **_: 0.90)  # strong Up

    engine.run_tick()
    snap = engine.state.snapshot()
    assert snap["ml"]["decision_source"] == "consensus_blocked"
    assert snap["signal"]["should_trade"] is False


def test_ml_only_mode_uses_ml_probability(monkeypatch):
    monkeypatch.setattr(config, "ML_TRADE_CONTROL_MODE", "ml_only")
    ml = StubMLModel(probability_up=0.10, ready=True)  # implies Down vs market 0.4
    engine, _, _ = _make_engine(ml_model=ml)
    monkeypatch.setattr("trading_engine.calc_up_probability", lambda **_: 0.90)  # baseline Up

    engine.run_tick()
    snap = engine.state.snapshot()
    assert snap["ml"]["decision_source"] == "ml_only"
    assert snap["signal"]["direction"] == "Down"
