"""GBM Monte Carlo probability model for 5-min BTC direction prediction."""

import numpy as np

import config


def estimate_volatility(candles):
    """Estimate annualized volatility from recent 1-min candle returns.

    Args:
        candles: list of candle dicts with 'close' key

    Returns:
        float: annualized volatility, or a default if insufficient data
    """
    if len(candles) < 2:
        return 0.005  # default ~0.5% per sqrt(minute)

    closes = np.array([c["close"] for c in candles])
    log_returns = np.diff(np.log(closes))

    if len(log_returns) == 0:
        return 0.005

    # Per-minute std, annualized (525600 minutes/year)
    return float(np.std(log_returns) * np.sqrt(525600))


def calc_short_term_drift(candles, lookback=5):
    """Estimate short-term momentum drift from last N 1-min returns.

    Args:
        candles: list of candle dicts
        lookback: number of recent candles to use

    Returns:
        float: annualized drift rate
    """
    if len(candles) < 2:
        return 0.0

    recent = candles[-lookback:]
    if len(recent) < 2:
        return 0.0

    closes = np.array([c["close"] for c in recent])
    log_returns = np.diff(np.log(closes))

    # Annualize the mean per-minute return
    return float(np.mean(log_returns) * 525600)


def calc_order_book_imbalance(bids, asks, depth_pct):
    """Compute order book imbalance within a given depth from mid price.

    Args:
        bids: list of [price, qty] sorted descending
        asks: list of [price, qty] sorted ascending
        depth_pct: fraction of mid price to include (e.g. 0.02 = 2%)

    Returns:
        float: imbalance in [-1, +1]. Positive = more bids (bullish).
    """
    if not bids or not asks:
        return 0.0

    mid_price = (bids[0][0] + asks[0][0]) / 2
    depth_range = mid_price * depth_pct

    bid_qty = sum(qty for price, qty in bids if price >= mid_price - depth_range)
    ask_qty = sum(qty for price, qty in asks if price <= mid_price + depth_range)

    total = bid_qty + ask_qty
    if total == 0:
        return 0.0

    return (bid_qty - ask_qty) / total


def calc_up_probability(current_price, window_open, time_left_sec, volatility,
                        obi_signal=0.0, drift=0.0):
    """Monte Carlo simulation of BTC price paths to estimate P(close >= open).

    Args:
        current_price: current BTC/USDT price
        window_open: price at the start of the 5-min window
        time_left_sec: seconds remaining in the window
        volatility: annualized volatility
        obi_signal: order book imbalance (-1 to +1), shifts drift
        drift: base annualized drift from momentum

    Returns:
        float: probability that price at window close >= window_open (0-1)
    """
    if time_left_sec <= 0:
        return 1.0 if current_price >= window_open else 0.0

    n_sims = config.MC_SIMULATIONS

    # Convert time to years for GBM
    dt = time_left_sec / (365.25 * 24 * 3600)

    # Adjust drift with OBI signal
    adjusted_drift = drift + obi_signal * config.OBI_DRIFT_WEIGHT * volatility

    # GBM: S_T = S_0 * exp((mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z)
    z = np.random.standard_normal(n_sims)
    log_change = (adjusted_drift - 0.5 * volatility ** 2) * dt + volatility * np.sqrt(dt) * z
    simulated_prices = current_price * np.exp(log_change)

    up_count = np.sum(simulated_prices >= window_open)
    return float(up_count / n_sims)
