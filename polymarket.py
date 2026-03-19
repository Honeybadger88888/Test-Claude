"""Polymarket Gamma + CLOB API client for 5-min BTC Up/Down markets."""

import json
import time
import requests
import config


class PolymarketClient:
    """Read-only client for discovering and pricing 5-min BTC markets."""

    def __init__(self):
        self.gamma_url = config.GAMMA_API_URL
        self.clob_url = config.CLOB_API_URL
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def get_current_window_ts(self):
        """Get the Unix timestamp for the current 5-min window (floored to 300s)."""
        now = int(time.time())
        return now - (now % 300)

    def get_window_end_ts(self):
        """Get the Unix timestamp when the current 5-min window closes."""
        return self.get_current_window_ts() + 300

    def get_current_market(self):
        """Fetch the current 5-min BTC Up/Down market from Polymarket.

        Returns:
            dict with keys: slug, up_token_id, down_token_id, end_time, question
            or None if market not found.
        """
        window_ts = self.get_current_window_ts()
        slug = f"btc-updown-5m-{window_ts}"

        try:
            resp = self.session.get(
                f"{self.gamma_url}/events",
                params={"slug": slug},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            print(f"[POLYMARKET] Error fetching market: {e}")
            return None

        if not data:
            return None

        for event in data:
            markets = event.get("markets", [])
            if not markets:
                continue

            market = markets[0]
            token_ids = json.loads(market.get("clobTokenIds", "[]"))
            outcomes = json.loads(market.get("outcomes", "[]"))

            if len(token_ids) < 2 or len(outcomes) < 2:
                continue

            # Map outcomes to token IDs (Up=first, Down=second typically)
            up_idx = 0
            down_idx = 1
            for i, outcome in enumerate(outcomes):
                if outcome.lower() in ("up", "yes"):
                    up_idx = i
                elif outcome.lower() in ("down", "no"):
                    down_idx = i

            return {
                "slug": slug,
                "up_token_id": token_ids[up_idx],
                "down_token_id": token_ids[down_idx],
                "end_time": market.get("endDate"),
                "question": market.get("question", ""),
                "condition_id": market.get("conditionId"),
            }

        return None

    def get_market_price(self, token_id, side="buy"):
        """Get the current price for a token (0-1, representing implied probability).

        Args:
            token_id: The CLOB token ID
            side: "buy" or "sell"

        Returns:
            float price (0-1) or None on error
        """
        try:
            resp = self.session.get(
                f"{self.clob_url}/price",
                params={"token_id": token_id, "side": side.upper()},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("price", 0))
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            print(f"[POLYMARKET] Error fetching price: {e}")
            return None

    def get_market_book(self, token_id):
        """Get the order book for a token.

        Returns:
            dict with 'bids' and 'asks' lists, or None on error
        """
        try:
            resp = self.session.get(
                f"{self.clob_url}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            print(f"[POLYMARKET] Error fetching book: {e}")
            return None

    def get_seconds_until_close(self):
        """Seconds remaining in the current 5-min window."""
        return max(0, self.get_window_end_ts() - int(time.time()))
