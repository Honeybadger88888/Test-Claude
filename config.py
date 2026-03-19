"""Configuration for the paper trading edge bot."""

# Trading parameters
EDGE_THRESHOLD = 0.05           # 5% minimum edge to place a trade
KELLY_FRACTION = 0.25           # Quarter-Kelly for safety
STARTING_BANKROLL = 10000.0     # Paper dollars
MAX_DAILY_LOSS_PCT = 0.05       # 5% daily stop-loss
MAX_CONSECUTIVE_LOSSES = 3      # Stop after N consecutive losses

# Model parameters
MC_SIMULATIONS = 5000           # Monte Carlo simulation paths
DECISION_SECS_BEFORE_CLOSE = 60 # Evaluate at T-60s before window close

# Depth analysis
DEPTH_LEVELS = [0.02, 0.05, 0.10]  # 2%, 5%, 10% from mid price
DEPTH_CALIBRATION_WINDOWS = 50     # Windows before auto-selecting best depth
OBI_DRIFT_WEIGHT = 0.3             # How much OBI shifts the drift term

# ML control
# Options: "baseline", "blended", "ml_only", "consensus"
ML_TRADE_CONTROL_MODE = "blended"

# Binance WebSocket (public, no auth)
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
BINANCE_WS_STREAMS = ["btcusdt@kline_1m", "btcusdt@depth20@100ms"]
CANDLE_BUFFER_SIZE = 30         # Rolling buffer of 1-min candles

# Coinbase fallback (for regions where Binance is restricted)
COINBASE_TICKER_URL = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
COINBASE_BOOK_URL = "https://api.exchange.coinbase.com/products/BTC-USD/book?level=2"
FALLBACK_POLL_INTERVAL_SEC = 1.0

# Polymarket API (public reads, no auth)
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"

# Logging
TRADE_LOG_DIR = "trades/"
