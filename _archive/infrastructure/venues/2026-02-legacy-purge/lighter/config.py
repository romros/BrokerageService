"""
Lighter Configuration

Loads configuration from environment variables for Lighter L3 venue.

Environment variables:
- LIGHTER_BASE_URL: API endpoint (e.g., https://testnet.zklighter.elliot.ai)
- LIGHTER_L1_ADDRESS: L1 wallet address (0x...)
- LIGHTER_L1_PRIVATE_KEY: L1 wallet private key (64 hex) - for API key registration
- LIGHTER_ACCOUNT_INDEX: Account index (e.g., 210)
- LIGHTER_API_KEY_INDEX: API key index (e.g., 1)
- LIGHTER_API_PRIVATE_KEY: API trading private key (80 hex) - for order signing

Critical: account_index and api_key_index MUST match between registration and signing.

References:
- Lab validation: lab/lighter/LIGHTER_COMPLETE_VALIDATION.md
- Production Pitfalls section: index consistency rules
"""

from dataclasses import dataclass
from typing import Dict
import os

from foundation.logging import get_logger

logger = get_logger(__name__)

# Default market mappings (order_book_id)
# Source: Lighter testnet UI + lab validation
DEFAULT_LIGHTER_MARKETS = {
    "WETH-USDC": 1,
    "BTC-USDC": 2,
    "LINK-USDC": 3,
}

# Market data tick interval (polling) for LiveMarketDataService pipeline
# Default 500ms; configurable via LIGHTER_TICK_INTERVAL_MS
DEFAULT_LIGHTER_TICK_INTERVAL_MS = 500

# Default base URLs per MARKET_DATA_ENV (when LIGHTER_BASE_URL not set)
# Source: apidocs.lighter.xyz, web search
DEFAULT_LIGHTER_BASE_URL_MAINNET = "https://mainnet.zklighter.elliot.ai"
DEFAULT_LIGHTER_BASE_URL_TESTNET = "https://testnet.zklighter.elliot.ai"


@dataclass(frozen=True)
class LighterConfig:
    """
    Lighter L3 configuration

    Attributes:
        base_url: API endpoint (testnet or mainnet)
        l1_address: L1 wallet address
        l1_private_key: L1 private key (64 hex) - for API key registration only
        account_index: Account index (consistent with registration)
        api_key_index: API key index (consistent with signing)
        api_private_key: API trading key (80 hex) - for order signing only
        markets: Symbol to order_book_id mapping
    """
    base_url: str
    l1_address: str
    l1_private_key: str  # 64 hex
    account_index: int
    api_key_index: int
    api_private_key: str  # 80 hex
    markets: Dict[str, int]

    def __post_init__(self):
        """Validate configuration"""
        # Validate base_url
        if not self.base_url:
            raise ValueError("LIGHTER_BASE_URL is required")

        if not self.base_url.startswith("http"):
            raise ValueError(f"LIGHTER_BASE_URL must start with http/https: {self.base_url}")

        # Validate addresses
        if not self.l1_address:
            raise ValueError("LIGHTER_L1_ADDRESS is required")

        if not self.l1_address.startswith("0x"):
            raise ValueError(f"LIGHTER_L1_ADDRESS must start with 0x: {self.l1_address}")

        # Validate indices
        if self.account_index < 0:
            raise ValueError(f"LIGHTER_ACCOUNT_INDEX must be >= 0: {self.account_index}")

        if self.api_key_index < 0:
            raise ValueError(f"LIGHTER_API_KEY_INDEX must be >= 0: {self.api_key_index}")

        # Keys validated in key_manager (length checks)

        logger.info(f"Lighter config loaded: base_url={self.base_url}, account_index={self.account_index}, api_key_index={self.api_key_index}")


def get_lighter_tick_interval_ms() -> int:
    """Tick interval in ms for Lighter price feed polling (from LIGHTER_TICK_INTERVAL_MS)."""
    try:
        return int(os.getenv("LIGHTER_TICK_INTERVAL_MS", str(DEFAULT_LIGHTER_TICK_INTERVAL_MS)))
    except ValueError:
        return DEFAULT_LIGHTER_TICK_INTERVAL_MS


def get_price_cache_ttl_s() -> float:
    """Price cache TTL (seconds). Testnet uses 5s to reduce 429s."""
    from foundation.config.constants import (  # lazy: evita circular config ↔ constants
        PRICE_CACHE_TTL_S_ENV,
        DEFAULT_PRICE_CACHE_TTL_S,
        DEFAULT_PRICE_CACHE_TTL_S_TESTNET,
    )
    env_val = os.getenv(PRICE_CACHE_TTL_S_ENV)
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    if os.getenv("MARKET_DATA_ENV", "mainnet").lower() == "testnet":
        return DEFAULT_PRICE_CACHE_TTL_S_TESTNET
    return DEFAULT_PRICE_CACHE_TTL_S


def get_price_stale_max_s() -> float:
    """Max staleness for cache fallback when 429 (seconds)."""
    from foundation.config.constants import PRICE_STALE_MAX_S_ENV, DEFAULT_PRICE_STALE_MAX_S  # lazy: evita circular config ↔ constants
    try:
        return float(os.getenv(PRICE_STALE_MAX_S_ENV, str(DEFAULT_PRICE_STALE_MAX_S)))
    except ValueError:
        return DEFAULT_PRICE_STALE_MAX_S


def get_price_fetch_deadline_s() -> float:
    """Max total wait for price fetch retries on 429 (seconds)."""
    from foundation.config.constants import PRICE_FETCH_DEADLINE_S_ENV, DEFAULT_PRICE_FETCH_DEADLINE_S  # lazy: evita circular config ↔ constants
    try:
        return float(os.getenv(PRICE_FETCH_DEADLINE_S_ENV, str(DEFAULT_PRICE_FETCH_DEADLINE_S)))
    except ValueError:
        return DEFAULT_PRICE_FETCH_DEADLINE_S


def get_lighter_symbols_from_env() -> list[str]:
    """
    Symbols for Lighter market data (from LIGHTER_SYMBOLS or SYMBOLS).
    Comma-separated, stripped; e.g. "ETH,BTC" or "XAUUSD,EURUSD".
    """
    raw = os.getenv("LIGHTER_SYMBOLS") or os.getenv("SYMBOLS") or "ETH,BTC"
    return [s.strip() for s in raw.split(",") if s.strip()]


def load_lighter_config_from_env() -> LighterConfig:
    """
    Load Lighter configuration from environment variables

    Base URL resolution:
    - LIGHTER_BASE_URL: if set, use it (explicit override)
    - Else: MARKET_DATA_ENV=mainnet → LIGHTER_BASE_URL_MAINNET or default mainnet
    - Else: MARKET_DATA_ENV=testnet → LIGHTER_BASE_URL_TESTNET or default testnet

    Returns:
        LighterConfig with validated settings

    Raises:
        ValueError: If required environment variables are missing or invalid
    """
    base_url = os.getenv("LIGHTER_BASE_URL")
    if not base_url:
        market_data_env = os.getenv("MARKET_DATA_ENV", "mainnet").lower()
        if market_data_env == "testnet":
            base_url = os.getenv(
                "LIGHTER_BASE_URL_TESTNET", DEFAULT_LIGHTER_BASE_URL_TESTNET
            )
        else:
            base_url = os.getenv(
                "LIGHTER_BASE_URL_MAINNET", DEFAULT_LIGHTER_BASE_URL_MAINNET
            )

    l1_address = os.getenv("LIGHTER_L1_ADDRESS")
    if not l1_address:
        raise ValueError(
            "LIGHTER_L1_ADDRESS environment variable is required. "
            "Your L1 wallet address (0x...)."
        )

    l1_private_key = os.getenv("LIGHTER_L1_PRIVATE_KEY")
    if not l1_private_key:
        raise ValueError(
            "LIGHTER_L1_PRIVATE_KEY environment variable is required. "
            "64 hex characters (with or without 0x prefix)."
        )

    api_private_key = os.getenv("LIGHTER_API_PRIVATE_KEY")
    if not api_private_key:
        raise ValueError(
            "LIGHTER_API_PRIVATE_KEY environment variable is required. "
            "80 hex characters (with or without 0x prefix)."
        )

    # Parse indices
    try:
        account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
    except ValueError as e:
        raise ValueError(f"LIGHTER_ACCOUNT_INDEX must be an integer: {e}")

    try:
        api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", "1"))
    except ValueError as e:
        raise ValueError(f"LIGHTER_API_KEY_INDEX must be an integer: {e}")

    # Load markets (use defaults for now)
    markets = DEFAULT_LIGHTER_MARKETS.copy()

    return LighterConfig(
        base_url=base_url,
        l1_address=l1_address,
        l1_private_key=l1_private_key,
        account_index=account_index,
        api_key_index=api_key_index,
        api_private_key=api_private_key,
        markets=markets,
    )
