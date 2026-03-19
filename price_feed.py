"""Binance WebSocket price feed for real-time BTC/USDT data."""

import json
import threading
import time
from collections import deque

import requests
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
        self._fallback_to_rest = False
        self._rest_session = requests.Session()
        self._active_candle = None

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
        self._rest_session.close()

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
            if self._fallback_to_rest:
                self._run_coinbase_rest_fallback()
                return

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
                if self._fallback_to_rest:
                    continue
                print(f"[PRICE_FEED] Reconnecting in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _on_open(self, ws):
        print("[PRICE_FEED] Connected to Binance WebSocket")
        self._connected.set()

    def _on_error(self, ws, error):
        print(f"[PRICE_FEED] WebSocket error: {error}")
        err = str(error).lower()
        if "restricted location" in err or "451" in err:
            print("[PRICE_FEED] Binance restricted, switching to Coinbase REST fallback.")
            self._fallback_to_rest = True

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

    def _run_coinbase_rest_fallback(self):
        """Fallback polling loop using Coinbase REST endpoints."""
        print("[PRICE_FEED] Running Coinbase REST fallback poller.")
        while self._running:
            try:
                ticker_resp = self._rest_session.get(config.COINBASE_TICKER_URL, timeout=8)
                book_resp = self._rest_session.get(config.COINBASE_BOOK_URL, timeout=8)
                ticker_resp.raise_for_status()
                book_resp.raise_for_status()

                ticker = ticker_resp.json()
                book = book_resp.json()

                price = float(ticker.get("price", 0) or 0)
                bids = [[float(p), float(q)] for p, q, *_ in book.get("bids", [])[:20]]
                asks = [[float(p), float(q)] for p, q, *_ in book.get("asks", [])[:20]]

                with self._lock:
                    if price > 0:
                        self._current_price = price
                    self._order_book["bids"] = sorted(bids, key=lambda x: -x[0])
                    self._order_book["asks"] = sorted(asks, key=lambda x: x[0])

                if price > 0:
                    self._update_fallback_candles(price)
                    self._connected.set()
            except Exception as e:
                print(f"[PRICE_FEED] Coinbase fallback poll error: {e}")
                self._connected.clear()

            time.sleep(config.FALLBACK_POLL_INTERVAL_SEC)

    def _update_fallback_candles(self, price):
        """Aggregate 1-second ticks into 1-minute synthetic candles."""
        now = int(time.time())
        minute_ts = now - (now % 60)

        if self._active_candle is None or self._active_candle["timestamp"] != minute_ts:
            if self._active_candle is not None:
                with self._lock:
                    self._candles.append(dict(self._active_candle))
            self._active_candle = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "timestamp": float(minute_ts),
            }
            return

        self._active_candle["high"] = max(self._active_candle["high"], price)
        self._active_candle["low"] = min(self._active_candle["low"], price)
        self._active_candle["close"] = price
