"""Tests for the probability model."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from model import (
    calc_up_probability,
    estimate_volatility,
    calc_short_term_drift,
    calc_order_book_imbalance,
)


class TestCalcUpProbability:
    def test_returns_between_0_and_1(self):
        p = calc_up_probability(50000, 50000, 60, 0.5)
        assert 0 <= p <= 1

    def test_price_well_above_open_high_prob(self):
        # Current price way above open with little time left → high probability
        p = calc_up_probability(51000, 50000, 10, 0.3)
        assert p > 0.8

    def test_price_well_below_open_low_prob(self):
        # Current price way below open with little time left → low probability
        p = calc_up_probability(49000, 50000, 10, 0.3)
        assert p < 0.2

    def test_price_equals_open_near_50(self):
        # Price at open with time left → should be near 50%
        p = calc_up_probability(50000, 50000, 60, 0.5)
        assert 0.3 < p < 0.7

    def test_zero_time_left_above(self):
        p = calc_up_probability(50001, 50000, 0, 0.5)
        assert p == 1.0

    def test_zero_time_left_below(self):
        p = calc_up_probability(49999, 50000, 0, 0.5)
        assert p == 0.0

    def test_positive_obi_increases_up_prob(self):
        np.random.seed(42)
        p_neutral = calc_up_probability(50000, 50000, 60, 0.5, obi_signal=0.0)
        np.random.seed(42)
        p_bullish = calc_up_probability(50000, 50000, 60, 0.5, obi_signal=0.8)
        assert p_bullish > p_neutral


class TestEstimateVolatility:
    def test_with_insufficient_data(self):
        assert estimate_volatility([]) == 0.005
        assert estimate_volatility([{"close": 100}]) == 0.005

    def test_with_constant_prices(self):
        candles = [{"close": 100.0}] * 10
        vol = estimate_volatility(candles)
        assert vol == 0.0

    def test_with_varying_prices(self):
        candles = [{"close": 100 + i * 0.1} for i in range(20)]
        vol = estimate_volatility(candles)
        assert vol > 0


class TestShortTermDrift:
    def test_upward_trend(self):
        candles = [{"close": 100 + i} for i in range(10)]
        drift = calc_short_term_drift(candles)
        assert drift > 0

    def test_downward_trend(self):
        candles = [{"close": 100 - i} for i in range(10)]
        drift = calc_short_term_drift(candles)
        assert drift < 0

    def test_insufficient_data(self):
        assert calc_short_term_drift([]) == 0.0
        assert calc_short_term_drift([{"close": 100}]) == 0.0


class TestOrderBookImbalance:
    def test_balanced_book(self):
        bids = [[100, 10], [99, 10]]
        asks = [[101, 10], [102, 10]]
        obi = calc_order_book_imbalance(bids, asks, 0.05)
        assert abs(obi) < 0.01  # roughly balanced

    def test_heavy_bids(self):
        bids = [[100, 100], [99, 100]]
        asks = [[101, 10], [102, 10]]
        obi = calc_order_book_imbalance(bids, asks, 0.05)
        assert obi > 0.5

    def test_heavy_asks(self):
        bids = [[100, 10], [99, 10]]
        asks = [[101, 100], [102, 100]]
        obi = calc_order_book_imbalance(bids, asks, 0.05)
        assert obi < -0.5

    def test_empty_book(self):
        assert calc_order_book_imbalance([], [], 0.05) == 0.0

    def test_narrow_depth_filters(self):
        # Very narrow depth should only capture closest levels
        bids = [[100, 10], [95, 1000]]  # far bid has huge qty
        asks = [[101, 10], [106, 1000]]  # far ask has huge qty
        obi_narrow = calc_order_book_imbalance(bids, asks, 0.02)
        obi_wide = calc_order_book_imbalance(bids, asks, 0.10)
        # Narrow should be more balanced since far levels are excluded
        assert abs(obi_narrow) < abs(obi_wide) or abs(obi_narrow - obi_wide) < 0.01
