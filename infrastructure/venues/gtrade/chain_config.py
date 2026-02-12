"""
gTrade Chain Configuration

Loads blockchain configuration from environment variables.
Supports Arbitrum mainnet and testnet.

Environment variables:
- ARBITRUM_RPC_URL: RPC endpoint URL
- ARBITRUM_CHAIN_ID: Chain ID (42161 for mainnet, 421614 for sepolia)
- WALLET_PRIVATE_KEY: Private key for signing transactions (optional for read-only)
- GTRADE_DIAMOND_ADDRESS: Main gTrade diamond contract address
- GTRADE_TRADING_ADDRESS: Trading contract address
- USDC_TOKEN_ADDRESS: USDC token contract address

References:
- https://docs.gains.trade/contracts
- https://docs.gains.trade/developer/integrators
"""


from dataclasses import dataclass
from typing import Optional
import os

from foundation.logging import get_logger


logger = get_logger(__name__)

# Default contract addresses for Arbitrum mainnet
# Source: https://docs.gains.trade/contracts
DEFAULT_ARBITRUM_MAINNET_ADDRESSES = {
    "diamond": "0xFF162c694eAA571f685030649814282eA457f169",  # gTrade Diamond
    "trading": "0xFF162c694eAA571f685030649814282eA457f169",  # Same as diamond (proxy pattern)
    "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",     # USDC on Arbitrum
}

# Default contract addresses for Arbitrum Sepolia testnet
DEFAULT_ARBITRUM_SEPOLIA_ADDRESSES = {
    "diamond": "0x0000000000000000000000000000000000000000",  # TODO: Add testnet addresses
    "trading": "0x0000000000000000000000000000000000000000",
    "usdc": "0x0000000000000000000000000000000000000000",
}


@dataclass(frozen=True)
class ContractAddresses:
    """
    gTrade contract addresses

    Attributes:
        diamond: Main gTrade diamond contract (proxy)
        trading: Trading facet contract
        usdc: USDC token contract
    """
    diamond: str
    trading: str
    usdc: str

    def __post_init__(self):
        """Validate addresses are checksummed"""
        from web3 import Web3

        for field_name in ["diamond", "trading", "usdc"]:
            address = getattr(self, field_name)
            if not Web3.is_checksum_address(address):
                # Auto-checksum if valid hex
                if Web3.is_address(address):
                    checksummed = Web3.to_checksum_address(address)
                    object.__setattr__(self, field_name, checksummed)
                    logger.warning(
                        f"Contract address '{field_name}' was not checksummed, "
                        f"converted to: {checksummed}"
                    )
                else:
                    raise ValueError(f"Invalid contract address for '{field_name}': {address}")


@dataclass(frozen=True)
class ChainConfig:
    """
    Blockchain configuration for gTrade

    Attributes:
        rpc_url: RPC endpoint URL
        chain_id: Chain ID (42161 = Arbitrum mainnet, 421614 = Arbitrum Sepolia)
        addresses: Contract addresses
        wallet_private_key: Private key for signing (optional, only for write operations)
    """
    rpc_url: str
    chain_id: int
    addresses: ContractAddresses
    wallet_private_key: Optional[str] = None

    @property
    def is_mainnet(self) -> bool:
        """Check if this is Arbitrum mainnet"""
        return self.chain_id == 42161

    @property
    def is_testnet(self) -> bool:
        """Check if this is Arbitrum Sepolia testnet"""
        return self.chain_id == 421614

    @property
    def network_name(self) -> str:
        """Get human-readable network name"""
        if self.is_mainnet:
            return "Arbitrum Mainnet"
        elif self.is_testnet:
            return "Arbitrum Sepolia Testnet"
        else:
            return f"Unknown Network (chain_id={self.chain_id})"

    @property
    def has_wallet(self) -> bool:
        """Check if wallet private key is configured"""
        return self.wallet_private_key is not None and len(self.wallet_private_key) > 0


def load_chain_config_from_env() -> ChainConfig:
    """
    Load chain configuration from environment variables

    Returns:
        ChainConfig instance

    Raises:
        ValueError: If required environment variables are missing or invalid
    """
    # Load RPC URL (required)
    rpc_url = os.getenv("ARBITRUM_RPC_URL")
    if not rpc_url:
        raise ValueError("ARBITRUM_RPC_URL environment variable is required")

    # Load chain ID (required)
    chain_id_str = os.getenv("ARBITRUM_CHAIN_ID", "42161")  # Default to mainnet
    try:
        chain_id = int(chain_id_str)
    except ValueError:
        raise ValueError(f"Invalid ARBITRUM_CHAIN_ID: {chain_id_str} (must be an integer)")

    # Select default addresses based on chain ID
    if chain_id == 42161:
        default_addresses = DEFAULT_ARBITRUM_MAINNET_ADDRESSES
    elif chain_id == 421614:
        default_addresses = DEFAULT_ARBITRUM_SEPOLIA_ADDRESSES
    else:
        logger.warning(f"Unknown chain ID {chain_id}, using mainnet addresses as fallback")
        default_addresses = DEFAULT_ARBITRUM_MAINNET_ADDRESSES

    # Load contract addresses (with defaults)
    diamond_address = os.getenv("GTRADE_DIAMOND_ADDRESS", default_addresses["diamond"])
    trading_address = os.getenv("GTRADE_TRADING_ADDRESS", default_addresses["trading"])
    usdc_address = os.getenv("USDC_TOKEN_ADDRESS", default_addresses["usdc"])

    addresses = ContractAddresses(
        diamond=diamond_address,
        trading=trading_address,
        usdc=usdc_address,
    )

    # Load wallet private key (optional - only needed for write operations)
    wallet_private_key = os.getenv("WALLET_PRIVATE_KEY")
    if wallet_private_key and not wallet_private_key.startswith("0x"):
        wallet_private_key = f"0x{wallet_private_key}"

    config = ChainConfig(
        rpc_url=rpc_url,
        chain_id=chain_id,
        addresses=addresses,
        wallet_private_key=wallet_private_key,
    )

    logger.info(
        f"Chain config loaded: network={config.network_name}, "
        f"has_wallet={config.has_wallet}, rpc_url={rpc_url[:50]}..."
    )

    return config
