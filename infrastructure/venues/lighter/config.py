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


def load_lighter_config_from_env() -> LighterConfig:
    """
    Load Lighter configuration from environment variables

    Returns:
        LighterConfig with validated settings

    Raises:
        ValueError: If required environment variables are missing or invalid
    """
    # Required variables
    base_url = os.getenv("LIGHTER_BASE_URL")
    if not base_url:
        raise ValueError(
            "LIGHTER_BASE_URL environment variable is required. "
            "Set to https://testnet.zklighter.elliot.ai for testnet."
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
