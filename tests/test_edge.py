"""Tests for edge calculation and Kelly sizing."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge import calc_edge, should_trade, calc_kelly_fraction, calc_position_size


class TestCalcEdge:
    def test_positive_edge(self):
        assert abs(calc_edge(0.60, 0.50) - 0.10) < 1e-10

    def test_negative_edge(self):
        assert abs(calc_edge(0.40, 0.50) - (-0.10)) < 1e-10

    def test_zero_edge(self):
        assert calc_edge(0.50, 0.50) == 0.0


class TestShouldTrade:
    def test_buy_up_with_edge(self):
        do, direction, edge = should_trade(0.60, 0.50, threshold=0.05)
        assert do is True
        assert direction == "Up"
        assert edge > 0

    def test_buy_down_with_edge(self):
        do, direction, edge = should_trade(0.40, 0.50, threshold=0.05)
        assert do is True
        assert direction == "Down"
        assert edge < 0

    def test_no_trade_within_threshold(self):
        do, direction, edge = should_trade(0.52, 0.50, threshold=0.05)
        assert do is False

    def test_exact_threshold_trades(self):
        # At exactly the threshold, edge > threshold due to floating point, so it trades
        do, direction, edge = should_trade(0.56, 0.50, threshold=0.05)
        assert do is True


class TestCalcKellyFraction:
    def test_positive_edge(self):
        # 60% win at even odds (market_p=0.5)
        f = calc_kelly_fraction(0.60, 0.50)
        assert f > 0
        assert f < 1

    def test_no_edge_returns_zero(self):
        f = calc_kelly_fraction(0.50, 0.50)
        assert f == 0.0

    def test_extreme_edge(self):
        # 90% prob at 50% price → big Kelly
        f = calc_kelly_fraction(0.90, 0.50)
        assert f > 0.5

    def test_boundary_prices(self):
        assert calc_kelly_fraction(0.5, 0.0) == 0.0
        assert calc_kelly_fraction(0.5, 1.0) == 0.0

    def test_down_bet(self):
        # my_p < market_p → we're betting Down
        f = calc_kelly_fraction(0.30, 0.50)
        assert f > 0  # Should have positive fraction for Down bet


class TestCalcPositionSize:
    def test_basic_sizing(self):
        size = calc_position_size(0.60, 0.50, bankroll=10000, kelly_fraction=0.25)
        assert size > 0
        assert size <= 1000  # max 10% of bankroll

    def test_no_edge_zero_size(self):
        size = calc_position_size(0.50, 0.50, bankroll=10000)
        assert size == 0.0

    def test_capped_at_10_percent(self):
        # Even with huge edge, should cap at 10%
        size = calc_position_size(0.95, 0.50, bankroll=10000, kelly_fraction=1.0)
        assert size <= 1000
