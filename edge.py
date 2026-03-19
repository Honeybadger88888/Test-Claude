"""Edge calculation and Kelly criterion position sizing."""

import config


def calc_edge(my_p, market_p):
    """Calculate the edge for the Up side.

    Args:
        my_p: model's probability of Up (0-1)
        market_p: market's implied probability of Up (0-1)

    Returns:
        float: edge (positive = buy Up is +EV, negative = buy Down is +EV)
    """
    return my_p - market_p


def should_trade(my_p, market_p, threshold=None):
    """Determine whether to trade and in which direction.

    Args:
        my_p: model's probability of Up
        market_p: market's implied probability of Up
        threshold: minimum edge to trade (default from config)

    Returns:
        tuple: (should_trade: bool, direction: str, edge: float)
    """
    if threshold is None:
        threshold = config.EDGE_THRESHOLD

    edge = calc_edge(my_p, market_p)

    if edge > threshold:
        return True, "Up", edge
    elif edge < -threshold:
        return True, "Down", edge
    else:
        return False, "None", edge


def calc_kelly_fraction(my_p, market_p):
    """Calculate the Kelly fraction for a binary bet.

    For a binary bet at odds implied by market_p:
        b = payout ratio = (1 / market_p) - 1  (for buying Up)
        f = (b * p - q) / b

    Args:
        my_p: model probability of winning
        market_p: price we'd pay (0-1)

    Returns:
        float: Kelly fraction (0 to 1), or 0 if no edge
    """
    if market_p <= 0 or market_p >= 1:
        return 0.0

    # If betting on Up: pay market_p, win (1 - market_p)
    # If betting on Down: pay (1 - market_p), win market_p
    if my_p > market_p:
        # Betting Up
        b = (1 / market_p) - 1  # payout ratio
        p = my_p
    else:
        # Betting Down
        b = (1 / (1 - market_p)) - 1
        p = 1 - my_p

    q = 1 - p
    f = (b * p - q) / b

    return max(0.0, f)


def calc_position_size(my_p, market_p, bankroll, kelly_fraction=None):
    """Calculate the dollar amount to risk on a trade.

    Args:
        my_p: model probability
        market_p: market price (implied prob)
        bankroll: current paper bankroll
        kelly_fraction: fraction of Kelly to use (default from config)

    Returns:
        float: dollar amount to bet
    """
    if kelly_fraction is None:
        kelly_fraction = config.KELLY_FRACTION

    full_kelly = calc_kelly_fraction(my_p, market_p)
    fraction = full_kelly * kelly_fraction

    # Cap at 10% of bankroll regardless
    fraction = min(fraction, 0.10)

    return bankroll * fraction
