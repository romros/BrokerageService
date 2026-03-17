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
CANDLE_STEP_SECONDS_1M = 60  # ts[i+1] - ts[i] per timeframe 1m
DEFAULT_CANDLES_LIMIT = 100
MAX_CANDLES_LIMIT = 10_000
DEFAULT_OHLCV_LIMIT = 1000  # /ohlcv/{symbol} default
DEFAULT_TRADES_LIMIT = 500
MAX_TRADES_LIMIT = 5000
KNOWN_VENUES = ("paper", "ostium", "lighter", "gtrade")

# Phase F: venues legacy opt-in (lighter, gtrade requereixen ENABLE_LEGACY_VENUES=1)
ENABLE_LEGACY_VENUES_ENV = "ENABLE_LEGACY_VENUES"
LEGACY_VENUES = ("lighter", "gtrade")  # Venues que requereixen opt-in explícit

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

# T7.1 Client-side SL/TP policy (paper + live)
PAPER_SL_PCT_ENV = "PAPER_SL_PCT"
DEFAULT_PAPER_SL_PCT = 2.0       # 2% SL per defecte
PAPER_TP_PCT_ENV = "PAPER_TP_PCT"
DEFAULT_PAPER_TP_PCT = 4.0       # 4% TP per defecte (RR 1:2)
PAPER_TTL_S_ENV = "PAPER_TTL_S"
DEFAULT_PAPER_TTL_S = 3600       # 1h TTL: forçar close si no toca SL/TP
PAPER_POLL_S_ENV = "PAPER_POLL_S"
DEFAULT_PAPER_POLL_S = 5         # Polling cada 5s per client-side monitor

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

# P7b: Compat registry (compat_probe output)
COMPAT_REGISTRY_RELATIVE_PATH = "compat_probe/compat_registry.json"

# Ostium compat (Ostium vs Dukascopy graduation gate)
OSTIUM_COMPAT_REGISTRY_RELATIVE_PATH = "compat_reports/ostium_compat_registry.json"
# T6.2: Artifact path canònic per compat reports (Dukascopy ↔ Ostium)
ARTIFACTS_COMPAT_DIR = "artifacts/compat"

# Ostium storage paths (TASCA 2; shared data_routes, backtest_market_data, mixed_ohlcv_stitcher)
REALTIME_DATALAYER_SUBDIR = "realtime_datalayer"
OSTIUM_BROKER_SUBDIR = "candles"
OSTIUM_CANONICAL_TZ = "America/New_York"
OSTIUM_PARQUET_SUBDIR = "historical_parquet_ostium_v1"

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

# P8.0 Read-through gap serving (response-only)
ENABLE_READ_THROUGH_ENV = "ENABLE_READ_THROUGH"
READ_THROUGH_MAX_MISSING_ENV = "READ_THROUGH_MAX_MISSING_MINUTES"
READ_THROUGH_TIMEOUT_ENV = "READ_THROUGH_PROVIDER_TIMEOUT_S"
DEFAULT_READ_THROUGH_MAX_MISSING = 30
DEFAULT_READ_THROUGH_TIMEOUT_S = 2.0

# Data Layer prod v0 (prefetch + writer + gates)
DATA_LAYER_ENABLED_ENV = "DATA_LAYER_ENABLED"
DATA_LAYER_PREFETCH_MINUTES_ENV = "DATA_LAYER_PREFETCH_MINUTES"
DATA_LAYER_WRITE_SYMBOLS_ENV = "DATA_LAYER_WRITE_SYMBOLS"
DATA_LAYER_GATES_MAX_GAP_S_ENV = "DATA_LAYER_GATES_MAX_GAP_S"
DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV = "DATA_LAYER_GATES_MAX_MISSING_PER_24H"
DATA_LAYER_STALE_SECONDS_ENV = "DATA_LAYER_STALE_SECONDS"
DATA_LAYER_STARTUP_GATE_ENV = "DATA_LAYER_STARTUP_GATE"
DATA_LAYER_WARMUP_MINUTES_ENV = "DATA_LAYER_WARMUP_MINUTES"
DEFAULT_DATA_LAYER_ENABLED = False
DEFAULT_DATA_LAYER_PREFETCH_MINUTES = 0
DEFAULT_DATA_LAYER_WARMUP_MINUTES = 120
DEFAULT_DATA_LAYER_GATES_MAX_GAP_S = 180
DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H = 1
DEFAULT_DATA_LAYER_STALE_SECONDS = 180

# Data Layer write mode: realtime (Lighter writer) | backfill_only (no ingest) | realtime_only | realtime_plus_backfill (Ostium ingest)
DATA_LAYER_WRITE_MODE_ENV = "DATA_LAYER_WRITE_MODE"
DEFAULT_DATA_LAYER_WRITE_MODE = "realtime"
DATA_LAYER_WRITE_MODES_OSTIUM_INGEST = ("realtime_only", "realtime_plus_backfill")

# Ostium (RWA price source, REST polling)
OSTIUM_ENABLED_ENV = "OSTIUM_ENABLED"
OSTIUM_SYMBOLS_ENV = "OSTIUM_SYMBOLS"
OSTIUM_QUARANTINE_SYMBOLS_ENV = "OSTIUM_QUARANTINE_SYMBOLS"
OSTIUM_POLL_S_ENV = "OSTIUM_POLL_S"
OSTIUM_PRICE_API_BASE_ENV = "OSTIUM_PRICE_API_BASE"
DEFAULT_OSTIUM_ENABLED = False
DEFAULT_OSTIUM_SYMBOLS = "EURUSD,GBPUSD"  # Allowlist: FX per defecte
DEFAULT_OSTIUM_QUARANTINE_SYMBOLS = ""  # Quarantine: buit per defecte (XAUUSD és PASS_BACKTEST T6.10)
DEFAULT_OSTIUM_POLL_S = 2
DEFAULT_OSTIUM_PRICE_API_BASE = "https://metadata-backend.ostium.io"

# Split vNext: SERVICE_ROLE per entrypoint (realtime_datalayer | historical_datalayer | trading_service)
SERVICE_ROLE_ENV = "SERVICE_ROLE"
VALID_SERVICE_ROLES = ("realtime_datalayer", "historical_datalayer", "trading_service")
DEFAULT_SERVICE_ROLE = None  # None = monolithic (legacy)

# Split vNext Phase 2: trading_service consumeix realtime_datalayer via HTTP
REALTIME_DATALAYER_BASE_URL_ENV = "REALTIME_DATALAYER_BASE_URL"
DEFAULT_REALTIME_DATALAYER_TIMEOUT_S = 5.0

# Realtime DataLayer v1: storage i retenció
REALTIME_DATALAYER_ROOT_ENV = "REALTIME_DATALAYER_ROOT"
REALTIME_CANDLES_MAX_HOURS_ENV = "REALTIME_CANDLES_MAX_HOURS"
REALTIME_TICKS_MAX_HOURS_ENV = "REALTIME_TICKS_MAX_HOURS"
DEFAULT_REALTIME_CANDLES_MAX_HOURS = 168
DEFAULT_REALTIME_TICKS_MAX_HOURS = 72

# Degraded backoff (non-blocking, autorecover)
OSTIUM_DEGRADED_BACKOFF_BASE_S_ENV = "OSTIUM_DEGRADED_BACKOFF_BASE_S"
OSTIUM_DEGRADED_BACKOFF_MAX_S_ENV = "OSTIUM_DEGRADED_BACKOFF_MAX_S"
DEFAULT_OSTIUM_DEGRADED_BACKOFF_BASE_S = 2
DEFAULT_OSTIUM_DEGRADED_BACKOFF_MAX_S = 60

# Market-hours heartbeat (Phase 3: no stop total quan mercat tancat)
# Quan market_closed, el símbol fa poll a interval reduït (heartbeat) sense escriure candles.
OSTIUM_CLOSED_HEARTBEAT_S_ENV = "OSTIUM_CLOSED_HEARTBEAT_S"
DEFAULT_OSTIUM_CLOSED_HEARTBEAT_S = 60  # 60s heartbeat quan mercat tancat


# Ostium tick recorder (forense, lab)
OSTIUM_TICK_RECORDER_ENABLED_ENV = "OSTIUM_TICK_RECORDER_ENABLED"
OSTIUM_TICK_RECORDER_OUTDIR_ENV = "OSTIUM_TICK_RECORDER_OUTDIR"
OSTIUM_TICK_RETENTION_DAYS_ENV = "OSTIUM_TICK_RETENTION_DAYS"
DEFAULT_OSTIUM_TICK_RECORDER_OUTDIR = "lab/out/ostium_forensics"
DEFAULT_OSTIUM_TICK_RETENTION_DAYS = 7

# Quality gates (trading_service → realtime_datalayer HTTP reader)
# Fail-closed: si headers crítics absents o dades dolentes → status="bad"; caller decideix NO_TRADE.
QUALITY_GATE_MAX_FRESHNESS_SEC_ENV = "QUALITY_GATE_MAX_FRESHNESS_SEC"
QUALITY_GATE_MIN_COMPLETENESS_ENV = "QUALITY_GATE_MIN_COMPLETENESS"
QUALITY_GATE_MAX_GAP_S_ENV = "QUALITY_GATE_MAX_GAP_S_GATE"
DATA_QUALITY_MAX_MISSING_MINUTES_ENV = "DATA_QUALITY_MAX_MISSING_MINUTES"
DEFAULT_QUALITY_GATE_MAX_FRESHNESS_SEC = 300   # 5 min (mercat tancat → ok si 0 gaps)
DEFAULT_QUALITY_GATE_MIN_COMPLETENESS = 0.95   # 95% cobertura mínima
DEFAULT_QUALITY_GATE_MAX_GAP_S = 180           # 3 min màxim gap acceptable

# T5.5: GET /positions ostium LIVE — timeout per evitar penjar (RPC chain)
OSTIUM_POSITIONS_TIMEOUT_S = 5

# T5.11a: open/close — timeout per wait receipt/reconcile; si timeout → 202 Accepted
TRADE_TX_WAIT_TIMEOUT_S_ENV = "TRADE_TX_WAIT_TIMEOUT_S"
DEFAULT_TRADE_TX_WAIT_TIMEOUT_S = 15

# T5.15: persistència operations — JSONL append-only, rehidratació a startup
OPERATIONS_JSONL_ENV = "OPERATIONS_JSONL_PATH"
DEFAULT_OPERATIONS_JSONL = "logs/operations.jsonl"
OPERATIONS_REHYDRATE_MAX_LINES = 5000

# T9.07: RAW Dukascopy M1 BI5 sync (immutable store + background worker)
RAW_SYNC_ENABLED_ENV = "RAW_SYNC_ENABLED"
RAW_SYNC_INTERVAL_MIN_ENV = "RAW_SYNC_INTERVAL_MIN"
RAW_SYNC_TAIL_DAYS_ENV = "RAW_SYNC_TAIL_DAYS"
RAW_SYNC_SYMBOLS_ENV = "SYMBOLS"  # Símbols per RAW sync (comma-separated)
DEFAULT_RAW_SYNC_ENABLED = False
DEFAULT_RAW_SYNC_INTERVAL_MIN = 60
DEFAULT_RAW_SYNC_TAIL_DAYS = 7
DEFAULT_RAW_SYNC_SYMBOLS = "EURUSD,XAUUSD"

# T9.18: Rang certificat SQ↔BS (source=dukascopy). Runner ha de demanar dins [FROM, TO).
DUKASCOPY_CERTIFIED_FROM_ENV = "DUKASCOPY_CERTIFIED_FROM"
DUKASCOPY_CERTIFIED_TO_ENV = "DUKASCOPY_CERTIFIED_TO"
DEFAULT_DUKASCOPY_CERTIFIED_FROM = "2023-06-15"  # Inici real SQ (ajustar segons GUI)
DEFAULT_DUKASCOPY_CERTIFIED_TO = "2026-01-28"   # Fi exclusive (SQ fins 2026-01-27 inclòs)
