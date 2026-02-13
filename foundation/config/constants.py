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
KNOWN_VENUES = ("lighter", "gtrade")

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

# ============================================
# WEBSOCKET & MESSAGING
# ============================================

# WebSocket hub configuration
DEFAULT_WS_BUFFER_SIZE = 1000  # Replay buffer size

# Price feed configuration
TICK_QUEUE_MAXSIZE = 1000      # Tick queue capacity
DEFAULT_TICKER_BROADCAST_MS = 200  # Ticker throttle interval (ms)

# ============================================
# BUSINESS LOGIC THRESHOLDS
# ============================================

# Candle analysis
DOJI_THRESHOLD_PERCENT = 0.1  # 10% body-to-range ratio for doji detection

# Fee placeholders (for future implementation)
BORROWING_FEE_PLACEHOLDER = 0.0  # TODO: Implement with OI data in Fase 6
DYNAMIC_SPREAD_PLACEHOLDER = 0.0  # TODO: Implement dynamic spread calculation
