"""Paper trading engine — simulated positions, P&L tracking, risk management."""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config


@dataclass
class Trade:
    """A single paper trade."""
    trade_id: int
    timestamp: float
    direction: str  # "Up" or "Down"
    size: float  # dollar amount risked
    market_p: float  # price paid (implied prob)
    my_p: float  # model probability
    edge: float
    window_slug: str = ""
    entry_price: float = 0.0  # BTC price at entry
    exit_price: float = 0.0  # BTC price at resolution
    result: str = ""  # "Win" or "Loss"
    pnl: float = 0.0
    bankroll_after: float = 0.0


class PaperTrader:
    """Manages paper trading portfolio with risk limits."""

    def __init__(self, bankroll=None):
        self.starting_bankroll = bankroll or config.STARTING_BANKROLL
        self.bankroll = self.starting_bankroll
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.trade_history: list[Trade] = []
        self._next_id = 1
        self._daily_reset_date = self._today()

    def open_trade(self, direction, size, market_p, my_p, edge,
                   window_slug="", entry_price=0.0):
        """Open a new paper trade.

        Args:
            direction: "Up" or "Down"
            size: dollar amount to risk
            market_p: Polymarket price paid
            my_p: model probability
            edge: calculated edge
            window_slug: Polymarket window slug
            entry_price: BTC price at time of trade

        Returns:
            Trade object
        """
        trade = Trade(
            trade_id=self._next_id,
            timestamp=time.time(),
            direction=direction,
            size=size,
            market_p=market_p,
            my_p=my_p,
            edge=edge,
            window_slug=window_slug,
            entry_price=entry_price,
        )
        self._next_id += 1
        return trade

    def resolve_trade(self, trade, actual_outcome, exit_price=0.0):
        """Resolve a trade based on the actual market outcome.

        Args:
            trade: Trade object from open_trade()
            actual_outcome: "Up" or "Down"
            exit_price: BTC price at window close

        Returns:
            Trade object updated with result and P&L
        """
        self._maybe_reset_daily()

        won = trade.direction == actual_outcome
        trade.exit_price = exit_price

        if won:
            # Paid market_p per share, each share pays $1
            if trade.direction == "Up":
                payout_ratio = (1 / trade.market_p) - 1
            else:
                payout_ratio = (1 / (1 - trade.market_p)) - 1
            trade.pnl = trade.size * payout_ratio
            trade.result = "Win"
            self.consecutive_losses = 0
        else:
            trade.pnl = -trade.size
            trade.result = "Loss"
            self.consecutive_losses += 1

        self.bankroll += trade.pnl
        self.daily_pnl += trade.pnl
        trade.bankroll_after = self.bankroll

        self.trade_history.append(trade)
        return trade

    def check_risk_limits(self):
        """Check if we can still trade today.

        Returns:
            tuple: (can_trade: bool, reason: str)
        """
        self._maybe_reset_daily()

        # Daily loss limit
        max_daily_loss = self.starting_bankroll * config.MAX_DAILY_LOSS_PCT
        if self.daily_pnl <= -max_daily_loss:
            return False, f"Daily loss limit hit ({self.daily_pnl:.2f})"

        # Consecutive losses
        if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
            return False, f"Consecutive loss limit hit ({self.consecutive_losses})"

        # Bankrupt
        if self.bankroll <= 0:
            return False, "Bankroll depleted"

        return True, "OK"

    def get_session_stats(self):
        """Get summary statistics for the current session."""
        if not self.trade_history:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "bankroll": self.bankroll,
                "daily_pnl": self.daily_pnl,
            }

        wins = sum(1 for t in self.trade_history if t.result == "Win")
        losses = sum(1 for t in self.trade_history if t.result == "Loss")
        pnls = [t.pnl for t in self.trade_history]

        return {
            "total_trades": len(self.trade_history),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(self.trade_history) if self.trade_history else 0.0,
            "total_pnl": sum(pnls),
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
            "bankroll": self.bankroll,
            "daily_pnl": self.daily_pnl,
        }

    def _today(self):
        return datetime.now(timezone.utc).date()

    def _maybe_reset_daily(self):
        today = self._today()
        if today != self._daily_reset_date:
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self._daily_reset_date = today
