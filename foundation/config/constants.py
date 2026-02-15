"""
Foundation Constants - Project-wide Constants

Single source of truth for configuration defaults and magic numbers
used across the entire BrokerageService project.

Categories:
- Timezone & Time
- Financial & Trading
- Network & API
- Storage & Data
- WebSocket & Messaging
"""


from zoneinfo import ZoneInfo


# ============================================
# TIMEZONE & TIME
# ============================================
CANONICAL_TIMEZONE_NAME = "America/New_York"
CANONICAL_TIMEZONE = ZoneInfo(CANONICAL_TIMEZONE_NAME)

# ============================================
# BROKER API (candles, trades, limits)
# ============================================
SUPPORTED_TIMEFRAME = "1m"
DEFAULT_CANDLES_LIMIT = 100
MAX_CANDLES_LIMIT = 10_000
DEFAULT_OHLCV_LIMIT = 1000  # /ohlcv/{symbol} default
DEFAULT_TRADES_LIMIT = 500
MAX_TRADES_LIMIT = 5000
KNOWN_VENUES = ("lighter", "gtrade", "paper")

# ============================================
# FINANCIAL & TRADING
# ============================================

# Basis points conversion: 100 bps = 1%, so divide by 10,000
BASIS_POINTS_DIVISOR = 10_000

# Default account settings (USDC)
DEFAULT_INITIAL_BALANCE_USDC = 10000.0

# Paper trading defaults
DEFAULT_PAPER_SLIPPAGE_PERCENT = 0.1  # 0.1% slippage
DEFAULT_PAPER_FEE_PERCENT = 0.05      # 0.05% generic fee

# P3.0 Paper Risk Engine
PAPER_MAINTENANCE_MARGIN_RATIO_ENV = "PAPER_MAINTENANCE_MARGIN_RATIO"
DEFAULT_PAPER_MAINTENANCE_MARGIN_RATIO = 0.05  # 5% maintenance margin (conservative)
PAPER_FEE_BPS_ENV = "PAPER_FEE_BPS"
DEFAULT_PAPER_FEE_BPS = 0  # 0 bps = no fee per default

# Backtest defaults
DEFAULT_BACKTEST_SPEED_MULTIPLIER = 1000  # 1000x speed
PRICE_POLL_INTERVAL_SECONDS = 30          # Seconds between price polls

# Mock values (when real data unavailable)
MOCK_TICK_VOLUME = 1.0  # Used when venue doesn't provide tick volume

# ============================================
# NETWORK & API
# ============================================

# Default API configuration
DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000

# Reconnection settings
DEFAULT_RECONNECT_DELAY_SECONDS = 5.0
DEFAULT_MAX_RECONNECT_ATTEMPTS = 0  # 0 = infinite
RECONNECT_BACKOFF_MAX_SECONDS = 60.0

# Timeout settings
MESSAGE_RECEIVE_TIMEOUT_SECONDS = 30.0

# ============================================
# STORAGE & DATA
# ============================================

# Default data paths
DEFAULT_DATAFILES_ROOT = "/datafiles"
DEFAULT_LOG_DIR = "logs"

# Storage tuning
MONTHS_TO_CHECK_BACKWARD = 12  # How many months to scan for files

# Gap validation
MAX_RANGE_SIZE_MINUTES = 1000  # Max size for chunking ranges
LOG_MAX_GAPS_TO_SHOW = 5       # Max gaps to display in logs

# SL/TP idempotency (P1.1)
SLTP_IDEMPOTENCY_PRECISION = 6  # Decimal places for idempotency key (round price)

# ============================================
# WEBSOCKET & MESSAGING
# ============================================

# WebSocket hub configuration
DEFAULT_WS_BUFFER_SIZE = 1000  # Replay buffer size

# Price feed configuration
TICK_QUEUE_MAXSIZE = 1000      # Tick queue capacity
DEFAULT_TICKER_BROADCAST_MS = 200  # Ticker throttle interval (ms)

# P3.1 Diagnostics (broker hang investigation)
TESTING_ENV = "TESTING"
BROKER_DIAG_ENV = "BROKER_DIAG"
HEARTBEAT_INTERVAL_S = 5

# Fake price feed (testing without network)
USE_FAKE_PRICE_FEED_ENV = "USE_FAKE_PRICE_FEED"
DEFAULT_FAKE_TICK_INTERVAL_MS = 500  # Fast ticks for integration tests

# Price cache (Lighter 429 rate-limit mitigation)
PRICE_CACHE_TTL_S_ENV = "PRICE_CACHE_TTL_S"
DEFAULT_PRICE_CACHE_TTL_S = 2.0
DEFAULT_PRICE_CACHE_TTL_S_TESTNET = 5.0
PRICE_STALE_MAX_S_ENV = "PRICE_STALE_MAX_S"
DEFAULT_PRICE_STALE_MAX_S = 10.0
PRICE_FETCH_DEADLINE_S_ENV = "PRICE_FETCH_DEADLINE_S"
DEFAULT_PRICE_FETCH_DEADLINE_S = 15.0

# WS Soak (P2.2 mainnet)
WS_SOAK_SYMBOLS_ENV = "WS_SOAK_SYMBOLS"
WS_SOAK_SECONDS_ENV = "WS_SOAK_SECONDS"
DEFAULT_WS_SOAK_SECONDS = 900  # 15 min
PREFERRED_SOAK_SYMBOLS = ("ETH", "BTC", "EURUSD", "XAU")  # Lighter (crypto + forex/metals)
PREFERRED_SOAK_SYMBOLS_GTRADE = ("EURUSD", "XAUUSD")  # gTrade forex/metals

# ============================================
# BUSINESS LOGIC THRESHOLDS
# ============================================

# Candle analysis
DOJI_THRESHOLD_PERCENT = 0.1  # 10% body-to-range ratio for doji detection

# Fee placeholders (for future implementation)
BORROWING_FEE_PLACEHOLDER = 0.0  # TODO: Implement with OI data in Fase 6
DYNAMIC_SPREAD_PLACEHOLDER = 0.0  # TODO: Implement dynamic spread calculation
