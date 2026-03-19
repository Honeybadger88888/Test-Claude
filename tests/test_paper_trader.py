"""Tests for the paper trading engine."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_trader import PaperTrader


class TestPaperTrader:
    def _make_trader(self, bankroll=10000):
        return PaperTrader(bankroll=bankroll)

    def test_initial_state(self):
        t = self._make_trader()
        assert t.bankroll == 10000
        assert t.daily_pnl == 0
        assert t.consecutive_losses == 0
        assert len(t.trade_history) == 0

    def test_winning_trade(self):
        t = self._make_trader()
        trade = t.open_trade("Up", 100, 0.50, 0.60, 0.10)
        result = t.resolve_trade(trade, "Up", exit_price=50100)

        assert result.result == "Win"
        assert result.pnl == 100.0  # paid $100 at 0.5, gets $200 back, profit = $100
        assert t.bankroll == 10100
        assert t.consecutive_losses == 0

    def test_losing_trade(self):
        t = self._make_trader()
        trade = t.open_trade("Up", 100, 0.50, 0.60, 0.10)
        result = t.resolve_trade(trade, "Down", exit_price=49900)

        assert result.result == "Loss"
        assert result.pnl == -100.0
        assert t.bankroll == 9900
        assert t.consecutive_losses == 1

    def test_down_bet_win(self):
        t = self._make_trader()
        trade = t.open_trade("Down", 100, 0.50, 0.40, -0.10)
        result = t.resolve_trade(trade, "Down", exit_price=49900)

        assert result.result == "Win"
        assert result.pnl == 100.0

    def test_consecutive_losses_tracked(self):
        t = self._make_trader()
        for _ in range(3):
            trade = t.open_trade("Up", 50, 0.50, 0.60, 0.10)
            t.resolve_trade(trade, "Down")
        assert t.consecutive_losses == 3

    def test_win_resets_consecutive_losses(self):
        t = self._make_trader()
        trade = t.open_trade("Up", 50, 0.50, 0.60, 0.10)
        t.resolve_trade(trade, "Down")
        assert t.consecutive_losses == 1

        trade = t.open_trade("Up", 50, 0.50, 0.60, 0.10)
        t.resolve_trade(trade, "Up")
        assert t.consecutive_losses == 0

    def test_risk_limit_daily_loss(self):
        t = self._make_trader(bankroll=1000)
        # Lose 5% of starting bankroll ($50)
        trade = t.open_trade("Up", 50, 0.50, 0.60, 0.10)
        t.resolve_trade(trade, "Down")

        can, reason = t.check_risk_limits()
        assert can is False
        assert "Daily loss" in reason

    def test_risk_limit_consecutive_losses(self):
        t = self._make_trader(bankroll=100000)
        for _ in range(3):
            trade = t.open_trade("Up", 10, 0.50, 0.60, 0.10)
            t.resolve_trade(trade, "Down")

        can, reason = t.check_risk_limits()
        assert can is False
        assert "Consecutive" in reason

    def test_risk_limit_bankrupt(self):
        t = self._make_trader(bankroll=100)
        trade = t.open_trade("Up", 100, 0.50, 0.60, 0.10)
        t.resolve_trade(trade, "Down")

        can, reason = t.check_risk_limits()
        assert can is False
        # Could hit daily loss or depleted — both are valid stops
        assert "Daily loss" in reason or "depleted" in reason

    def test_session_stats(self):
        t = self._make_trader()
        trade = t.open_trade("Up", 100, 0.50, 0.60, 0.10)
        t.resolve_trade(trade, "Up")
        trade = t.open_trade("Up", 100, 0.50, 0.60, 0.10)
        t.resolve_trade(trade, "Down")

        stats = t.get_session_stats()
        assert stats["total_trades"] == 2
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["win_rate"] == 0.5

    def test_empty_stats(self):
        t = self._make_trader()
        stats = t.get_session_stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0
