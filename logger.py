"""Dual logging: colored console output + CSV file for trade records."""

import csv
import os
import time
from datetime import datetime, timezone

import config


# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class TradeLogger:
    """Logs trades and skips to console (colored) and CSV file."""

    def __init__(self):
        self._csv_path = os.path.join(config.TRADE_LOG_DIR, "trades.csv")
        self._csv_initialized = False
        os.makedirs(config.TRADE_LOG_DIR, exist_ok=True)

    def log_trade(self, trade):
        """Log a resolved trade to console and CSV.

        Args:
            trade: Trade object with result, pnl, etc.
        """
        ts = datetime.fromtimestamp(trade.timestamp, tz=timezone.utc).strftime("%H:%M:%S")

        if trade.result == "Win":
            color = GREEN
            symbol = "+"
        else:
            color = RED
            symbol = ""

        console_msg = (
            f"{color}{BOLD}[{ts}] {trade.result.upper()}{RESET} "
            f"{trade.direction} | "
            f"my_p={trade.my_p:.3f} mkt={trade.market_p:.3f} "
            f"edge={trade.edge:+.3f} | "
            f"size=${trade.size:.2f} "
            f"PnL={color}{symbol}{trade.pnl:.2f}{RESET} | "
            f"Bankroll=${trade.bankroll_after:.2f}"
        )
        print(console_msg)

        self._write_csv(trade)

    def log_skip(self, reason, my_p=None, market_p=None, edge=None):
        """Log a skipped window to console.

        Args:
            reason: why we skipped (e.g. "no edge", "risk limit")
            my_p: model probability (if available)
            market_p: market probability (if available)
            edge: calculated edge (if available)
        """
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

        parts = [f"{YELLOW}[{ts}] SKIP{RESET} {reason}"]
        if my_p is not None:
            parts.append(f"my_p={my_p:.3f}")
        if market_p is not None:
            parts.append(f"mkt={market_p:.3f}")
        if edge is not None:
            parts.append(f"edge={edge:+.3f}")

        print(" | ".join(parts))

    def log_depth_analysis(self, analysis_str):
        """Log depth analysis comparison line.

        Args:
            analysis_str: formatted string from DepthAnalyzer.format_comparison()
        """
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"{CYAN}[{ts}] {analysis_str}{RESET}")

    def log_window_start(self, slug, open_price):
        """Log the start of a new 5-min window."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n{BOLD}[{ts}] === Window: {slug} | Open: ${open_price:,.2f} ==={RESET}")

    def log_summary(self, stats):
        """Log session summary statistics."""
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}SESSION SUMMARY{RESET}")
        print(f"{'='*60}")
        print(f"  Total Trades:  {stats['total_trades']}")
        print(f"  Wins:          {stats['wins']}")
        print(f"  Losses:        {stats['losses']}")
        print(f"  Win Rate:      {stats['win_rate']:.1%}")
        print(f"  Total PnL:     ${stats['total_pnl']:+.2f}")
        if stats['total_trades'] > 0:
            print(f"  Best Trade:    ${stats['best_trade']:+.2f}")
            print(f"  Worst Trade:   ${stats['worst_trade']:+.2f}")
        print(f"  Bankroll:      ${stats['bankroll']:.2f}")
        print(f"  Daily PnL:     ${stats['daily_pnl']:+.2f}")
        print(f"{'='*60}\n")

    def _write_csv(self, trade):
        """Append trade to CSV file."""
        write_header = not self._csv_initialized and not os.path.exists(self._csv_path)

        with open(self._csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow([
                    "timestamp", "window_slug", "direction",
                    "my_p", "market_p", "edge",
                    "size", "entry_price", "exit_price",
                    "result", "pnl", "bankroll_after",
                ])
                self._csv_initialized = True

            writer.writerow([
                datetime.fromtimestamp(trade.timestamp, tz=timezone.utc).isoformat(),
                trade.window_slug,
                trade.direction,
                f"{trade.my_p:.6f}",
                f"{trade.market_p:.6f}",
                f"{trade.edge:.6f}",
                f"{trade.size:.2f}",
                f"{trade.entry_price:.2f}",
                f"{trade.exit_price:.2f}",
                trade.result,
                f"{trade.pnl:.2f}",
                f"{trade.bankroll_after:.2f}",
            ])
