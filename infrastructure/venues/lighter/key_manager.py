"""
Lighter Key Management

Validates and manages Lighter's two-key authentication system:
1. L1 wallet key (64 hex) - for API key registration/rotation
2. API trading key (80 hex) - for order signing

Critical rules (from lab validation):
- L1 key: standard Ethereum private key (64 hex chars)
- API key: Lighter-specific key (80 hex chars)
- Never mix keys across environments (testnet vs mainnet)
- account_index and api_key_index must be consistent

References:
- lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Production Pitfalls section
"""

from typing import Optional
import re

from foundation.logging import get_logger

logger = get_logger(__name__)


def validate_l1_private_key(key: str) -> str:
    """
    Validate and normalize L1 wallet private key

    Args:
        key: Private key (64 hex, optional 0x prefix)

    Returns:
        Normalized key (64 hex, no prefix)

    Raises:
        ValueError: If key is invalid
    """
    if not key:
        raise ValueError("L1 private key cannot be empty")

    # Remove 0x prefix if present
    normalized = key.lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]

    # Check length
    if len(normalized) != 64:
        raise ValueError(
            f"L1 private key must be 64 hex characters (got {len(normalized)}). "
            "This is a standard Ethereum wallet private key."
        )

    # Check hex
    if not re.match(r'^[0-9a-f]{64}$', normalized):
        raise ValueError(
            "L1 private key must contain only hexadecimal characters (0-9, a-f). "
            f"Invalid characters found."
        )

    return normalized


def validate_api_private_key(key: str) -> str:
    """
    Validate and normalize API trading private key

    Args:
        key: API private key (80 hex, optional 0x prefix)

    Returns:
        Normalized key (80 hex, no prefix)

    Raises:
        ValueError: If key is invalid
    """
    if not key:
        raise ValueError("API private key cannot be empty")

    # Remove 0x prefix if present
    normalized = key.lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]

    # Check length
    if len(normalized) != 80:
        raise ValueError(
            f"API private key must be 80 hex characters (got {len(normalized)}). "
            "This is a Lighter-specific API trading key, NOT the L1 wallet key."
        )

    # Check hex
    if not re.match(r'^[0-9a-f]{80}$', normalized):
        raise ValueError(
            "API private key must contain only hexadecimal characters (0-9, a-f). "
            f"Invalid characters found."
        )

    return normalized


def validate_account_index(index: int) -> int:
    """
    Validate account index (uint32 range)

    Args:
        index: Account index (0 to 2^32-1)

    Returns:
        The validated index

    Raises:
        ValueError: If index is out of uint32 range
    """
    if not isinstance(index, int):
        raise TypeError(f"Account index must be an integer (got {type(index).__name__})")

    if index < 0 or index >= 2**32:
        raise ValueError(
            f"Account index must be in uint32 range [0, {2**32-1}] (got {index}). "
            "Typical value is 210 for testnet."
        )

    return index


def validate_api_key_index(index: int) -> int:
    """
    Validate API key index (uint32 range)

    Args:
        index: API key index (0 to 2^32-1)

    Returns:
        The validated index

    Raises:
        ValueError: If index is out of uint32 range
    """
    if not isinstance(index, int):
        raise TypeError(f"API key index must be an integer (got {type(index).__name__})")

    if index < 0 or index >= 2**32:
        raise ValueError(
            f"API key index must be in uint32 range [0, {2**32-1}] (got {index}). "
            "Typical value is 1. This must match the index used during API key registration."
        )

    return index


def build_signer_client(config):
    """
    Build Lighter SignerClient for order signing

    Args:
        config: LighterConfig instance

    Returns:
        SignerClient instance (lazy import to avoid dependency if not using Lighter)

    Note:
        This does NOT perform trading operations, only initializes the client
        for health checks and future trading operations.
    """
    try:
        # Lazy import to avoid requiring lighter SDK if not using Lighter venue
        from lighter import SignerClient
    except ImportError as e:
        raise ImportError(
            "lighter SDK not installed. Install with: pip install lighter-python-sdk"
        ) from e

    # Validate keys before building client
    validate_api_key_index(config.api_key_index)
    api_private_key_normalized = validate_api_private_key(config.api_private_key)

    # Build client
    # Note: SignerClient expects api_private_keys as dict {index: key}
    try:
        client = SignerClient(
            base_url=config.base_url,
            account_index=config.account_index,
            api_private_keys={config.api_key_index: api_private_key_normalized}
        )
        logger.info(f"SignerClient initialized: account_index={config.account_index}, api_key_index={config.api_key_index}")
        return client
    except Exception as e:
        logger.error(f"Failed to build SignerClient: {e}")
        raise ValueError(
            f"Failed to initialize Lighter SignerClient: {e}. "
            "Check that account_index and api_key_index match your registered API key."
        ) from e
