"""CLI runner for the continuous auto paper-trading engine."""

import signal
import sys
import time

import config
from trading_engine import TradingEngine


def main():
    print("=" * 60)
    print("  PAPER TRADING EDGE BOT (AUTO)")
    print("  Polymarket 5-min BTC Up/Down")
    print(f"  Bankroll: ${config.STARTING_BANKROLL:,.2f}")
    print(f"  Edge threshold: {config.EDGE_THRESHOLD:.0%}")
    print(f"  Kelly fraction: {config.KELLY_FRACTION:.0%}")
    print("=" * 60)

    engine = TradingEngine(auto_trade=True, poll_interval_sec=1.0)

    def shutdown(sig, frame):
        print("\n\nShutting down...")
        engine.stop()
        stats = engine.trader.get_session_stats()
        engine.log.log_summary(stats)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    engine.start()
    print("Engine running. Press Ctrl+C to stop.")

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
