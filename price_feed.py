"""Binance WebSocket price feed for real-time BTC/USDT data."""

import json
import threading
import time
from collections import deque

import websocket

import config


class PriceFeed:
    """Connects to Binance public WebSocket for 1-min candles and order book depth."""

    def __init__(self):
        self._candles = deque(maxlen=config.CANDLE_BUFFER_SIZE)
        self._current_price = None
        self._order_book = {"bids": [], "asks": []}
        self._lock = threading.Lock()
        self._ws = None
        self._ws_thread = None
        self._running = False
        self._connected = threading.Event()

    def start(self):
        """Start the WebSocket connection in a background thread."""
        self._running = True
        self._ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self._ws_thread.start()

    def stop(self):
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            self._ws.close()

    def wait_for_connection(self, timeout=30):
        """Block until connected or timeout."""
        return self._connected.wait(timeout=timeout)

    def get_current_price(self):
        """Get the latest BTC/USDT price."""
        with self._lock:
            return self._current_price

    def get_recent_candles(self, n=None):
        """Get recent 1-min candles as list of dicts.

        Each candle: {open, high, low, close, volume, timestamp}
        """
        with self._lock:
            candles = list(self._candles)
        if n is not None:
            candles = candles[-n:]
        return candles

    def get_order_book(self):
        """Get the current order book snapshot.

        Returns:
            dict with 'bids' and 'asks', each a list of [price, qty] pairs
            sorted by price (bids descending, asks ascending).
        """
        with self._lock:
            return {
                "bids": list(self._order_book["bids"]),
                "asks": list(self._order_book["asks"]),
            }

    def _run_ws(self):
        """WebSocket connection loop with auto-reconnect."""
        backoff = 1
        while self._running:
            try:
                streams = "/".join(config.BINANCE_WS_STREAMS)
                url = f"{config.BINANCE_WS_URL}/{streams}"
                self._ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                print(f"[PRICE_FEED] WebSocket error: {e}")

            if self._running:
                self._connected.clear()
                print(f"[PRICE_FEED] Reconnecting in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _on_open(self, ws):
        print("[PRICE_FEED] Connected to Binance WebSocket")
        self._connected.set()

    def _on_error(self, ws, error):
        print(f"[PRICE_FEED] WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[PRICE_FEED] WebSocket closed: {close_status_code} {close_msg}")
        self._connected.clear()

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        stream = data.get("stream", "")
        payload = data.get("data", data)

        if "kline" in stream or "k" in payload:
            self._handle_kline(payload)
        elif "depth" in stream or "bids" in payload:
            self._handle_depth(payload)

    def _handle_kline(self, data):
        """Process a kline/candlestick message."""
        k = data.get("k", data)
        if not k:
            return

        price = float(k.get("c", 0))  # close price
        with self._lock:
            self._current_price = price

        # Only store completed candles
        if k.get("x", False):  # candle closed
            candle = {
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "timestamp": k["t"] / 1000,  # ms to seconds
            }
            with self._lock:
                self._candles.append(candle)

    def _handle_depth(self, data):
        """Process an order book depth message."""
        bids = [[float(p), float(q)] for p, q in data.get("bids", data.get("b", []))]
        asks = [[float(p), float(q)] for p, q in data.get("asks", data.get("a", []))]

        with self._lock:
            self._order_book["bids"] = sorted(bids, key=lambda x: -x[0])
            self._order_book["asks"] = sorted(asks, key=lambda x: x[0])
            if bids and not self._current_price:
                self._current_price = bids[0][0]
