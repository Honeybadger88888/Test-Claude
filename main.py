"""Paper Trading Edge Bot — Entry point.

Monitors Polymarket 5-min BTC Up/Down markets, calculates probability
via Monte Carlo + order book analysis, and paper-trades when edge exists.

Usage:
    python main.py
"""

import signal
import sys
import time

import config
from polymarket import PolymarketClient
from price_feed import PriceFeed
from model import calc_up_probability, estimate_volatility, calc_short_term_drift
from depth_analyzer import DepthAnalyzer
from edge import should_trade, calc_position_size, calc_edge
from paper_trader import PaperTrader
from logger import TradeLogger


def main():
    print("=" * 60)
    print("  PAPER TRADING EDGE BOT")
    print("  Polymarket 5-min BTC Up/Down")
    print(f"  Bankroll: ${config.STARTING_BANKROLL:,.2f}")
    print(f"  Edge threshold: {config.EDGE_THRESHOLD:.0%}")
    print(f"  Kelly fraction: {config.KELLY_FRACTION:.0%}")
    print("=" * 60)

    # Initialize components
    poly = PolymarketClient()
    feed = PriceFeed()
    analyzer = DepthAnalyzer()
    trader = PaperTrader()
    log = TradeLogger()

    # Graceful shutdown
    def shutdown(sig, frame):
        print("\n\nShutting down...")
        feed.stop()
        log.log_summary(trader.get_session_stats())
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start price feed
    print("\nConnecting to Binance WebSocket...")
    feed.start()
    if not feed.wait_for_connection(timeout=30):
        print("ERROR: Could not connect to Binance WebSocket")
        sys.exit(1)
    print("Connected. Waiting for initial price data...\n")

    # Wait for first price
    for _ in range(30):
        if feed.get_current_price() is not None:
            break
        time.sleep(1)

    if feed.get_current_price() is None:
        print("ERROR: No price data received")
        sys.exit(1)

    # Main trading loop
    while True:
        try:
            _run_window(poly, feed, analyzer, trader, log)
        except KeyboardInterrupt:
            shutdown(None, None)
        except Exception as e:
            print(f"\n[ERROR] Window failed: {e}")
            import traceback
            traceback.print_exc()
            # Wait for next window
            secs_left = poly.get_seconds_until_close()
            if secs_left > 0:
                time.sleep(secs_left)


def _run_window(poly, feed, analyzer, trader, log):
    """Execute one 5-minute trading window cycle."""

    # === Phase 1: Wait for new window to start ===
    secs_left = poly.get_seconds_until_close()
    if secs_left > config.DECISION_SECS_BEFORE_CLOSE:
        # Wait until decision point
        wait_time = secs_left - config.DECISION_SECS_BEFORE_CLOSE
        # But first, log the window start
        window_ts = poly.get_current_window_ts()
        open_price = feed.get_current_price()
        slug = f"btc-updown-5m-{window_ts}"
        if open_price:
            log.log_window_start(slug, open_price)
        print(f"  Waiting {wait_time:.0f}s until decision point...")
        time.sleep(wait_time)
    elif secs_left <= 5:
        # Too close to close, wait for next window
        time.sleep(secs_left + 1)
        return

    # === Phase 2: Fetch Polymarket market ===
    market = poly.get_current_market()
    if market is None:
        log.log_skip("No Polymarket market found")
        time.sleep(poly.get_seconds_until_close() + 1)
        return

    slug = market["slug"]
    window_ts = poly.get_current_window_ts()

    # === Phase 3: Gather data at decision point ===
    current_price = feed.get_current_price()
    if current_price is None:
        log.log_skip("No price data")
        time.sleep(poly.get_seconds_until_close() + 1)
        return

    # Get order book and compute multi-depth OBI
    book = feed.get_order_book()
    obi_values = analyzer.calc_all_obis(book)
    depth_record = analyzer.record_prediction(time.time(), obi_values)

    # Log depth analysis
    log.log_depth_analysis(analyzer.format_comparison())

    # Get Polymarket price (market_p)
    market_p = poly.get_market_price(market["up_token_id"])
    if market_p is None or market_p <= 0 or market_p >= 1:
        market_p = 0.5  # fallback to 50/50

    # Compute model probability
    candles = feed.get_recent_candles()
    volatility = estimate_volatility(candles)
    drift = calc_short_term_drift(candles)
    best_obi = analyzer.get_best_obi(obi_values)
    time_left = poly.get_seconds_until_close()

    # Use the window open price (approximate: price at start of this 5-min block)
    # In practice, we'd track the exact open, but current_price at T=0 is close
    window_open = current_price  # simplified — ideally tracked from T=0

    my_p = calc_up_probability(
        current_price=current_price,
        window_open=window_open,
        time_left_sec=time_left,
        volatility=volatility,
        obi_signal=best_obi,
        drift=drift,
    )

    # === Phase 4: Edge check and trade decision ===
    edge = calc_edge(my_p, market_p)
    do_trade, direction, edge_val = should_trade(my_p, market_p)

    # Check risk limits
    can_trade, risk_reason = trader.check_risk_limits()

    if do_trade and can_trade:
        size = calc_position_size(my_p, market_p, trader.bankroll)
        if size < 1.0:
            log.log_skip("Position too small", my_p, market_p, edge)
        else:
            trade = trader.open_trade(
                direction=direction,
                size=size,
                market_p=market_p,
                my_p=my_p,
                edge=edge_val,
                window_slug=slug,
                entry_price=current_price,
            )
            print(
                f"  TRADE OPENED: {direction} | "
                f"size=${size:.2f} | "
                f"my_p={my_p:.3f} mkt={market_p:.3f} edge={edge_val:+.3f}"
            )

            # === Phase 5: Wait for resolution ===
            remaining = poly.get_seconds_until_close()
            if remaining > 0:
                time.sleep(remaining + 2)  # +2s buffer for price to settle

            # Get closing price
            exit_price = feed.get_current_price() or current_price

            # Determine outcome: did price go up or down over the window?
            actual_outcome = "Up" if exit_price >= window_open else "Down"

            # Record depth outcome
            analyzer.record_outcome(actual_outcome)
            log.log_depth_analysis(analyzer.format_comparison())

            # Resolve trade
            resolved = trader.resolve_trade(trade, actual_outcome, exit_price)
            log.log_trade(resolved)

            # Periodic summary every 10 trades
            if len(trader.trade_history) % 10 == 0:
                log.log_summary(trader.get_session_stats())

            return  # Done with this window

    elif not can_trade:
        log.log_skip(f"Risk limit: {risk_reason}", my_p, market_p, edge)
    else:
        log.log_skip("No edge", my_p, market_p, edge)

    # === No trade — still wait for resolution to track depth accuracy ===
    remaining = poly.get_seconds_until_close()
    if remaining > 0:
        time.sleep(remaining + 2)

    exit_price = feed.get_current_price() or current_price
    actual_outcome = "Up" if exit_price >= window_open else "Down"
    analyzer.record_outcome(actual_outcome)


if __name__ == "__main__":
    main()
