"""
Unit test: ChainConfig (env loading + validation)

Tests chain configuration loading and validation:
- Environment variable loading
- ChainConfig validation
- Address checksumming
- Default values for mainnet/testnet
"""


from unittest.mock import patch
import os

from infrastructure.venues.gtrade.chain_config import (


    ChainConfig,
    ContractAddresses,
    load_chain_config_from_env,
    DEFAULT_ARBITRUM_MAINNET_ADDRESSES,
)

def test_contract_addresses_checksumming():
    """Test that addresses are auto-checksummed"""
    # Lowercase address should be checksummed
    addresses = ContractAddresses(
        diamond="0xff162c694eaa571f685030649814282ea457f169",
        trading="0xff162c694eaa571f685030649814282ea457f169",
        usdc="0xaf88d065e77c8cc2239327c5edb3a432268e5831",
    )

    # Should be checksummed
    assert addresses.diamond == "0xFF162c694eAA571f685030649814282eA457f169"
    assert addresses.trading == "0xFF162c694eAA571f685030649814282eA457f169"
    assert addresses.usdc == "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"

    print("✓ Contract addresses auto-checksum")


def test_chain_config_mainnet():
    """Test mainnet configuration"""
    addresses = ContractAddresses(**DEFAULT_ARBITRUM_MAINNET_ADDRESSES)

    config = ChainConfig(
        rpc_url="https://arb1.arbitrum.io/rpc",
        chain_id=42161,
        addresses=addresses,
    )

    assert config.is_mainnet is True
    assert config.is_testnet is False
    assert config.network_name == "Arbitrum Mainnet"
    assert config.has_wallet is False

    print("✓ ChainConfig mainnet detection")


def test_chain_config_testnet():
    """Test testnet configuration"""
    addresses = ContractAddresses(
        diamond="0x0000000000000000000000000000000000000001",
        trading="0x0000000000000000000000000000000000000002",
        usdc="0x0000000000000000000000000000000000000003",
    )

    config = ChainConfig(
        rpc_url="https://sepolia-rollup.arbitrum.io/rpc",
        chain_id=421614,
        addresses=addresses,
    )

    assert config.is_mainnet is False
    assert config.is_testnet is True
    assert config.network_name == "Arbitrum Sepolia Testnet"

    print("✓ ChainConfig testnet detection")


def test_chain_config_with_wallet():
    """Test configuration with wallet"""
    addresses = ContractAddresses(**DEFAULT_ARBITRUM_MAINNET_ADDRESSES)

    config = ChainConfig(
        rpc_url="https://arb1.arbitrum.io/rpc",
        chain_id=42161,
        addresses=addresses,
        wallet_private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    )

    assert config.has_wallet is True

    print("✓ ChainConfig with wallet")


def test_load_from_env_mainnet():
    """Test loading configuration from environment (mainnet)"""
    env = {
        "ARBITRUM_RPC_URL": "https://arb1.arbitrum.io/rpc",
        "ARBITRUM_CHAIN_ID": "42161",
    }

    with patch.dict(os.environ, env, clear=False):
        config = load_chain_config_from_env()

    assert config.rpc_url == "https://arb1.arbitrum.io/rpc"
    assert config.chain_id == 42161
    assert config.is_mainnet is True
    assert config.addresses.diamond == DEFAULT_ARBITRUM_MAINNET_ADDRESSES["diamond"]

    print("✓ Load config from env (mainnet)")


def test_load_from_env_with_wallet():
    """Test loading configuration with wallet key"""
    env = {
        "ARBITRUM_RPC_URL": "https://arb1.arbitrum.io/rpc",
        "ARBITRUM_CHAIN_ID": "42161",
        "WALLET_PRIVATE_KEY": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    }

    with patch.dict(os.environ, env, clear=False):
        config = load_chain_config_from_env()

    assert config.has_wallet is True
    # Should add 0x prefix
    assert config.wallet_private_key.startswith("0x")

    print("✓ Load config from env (with wallet)")


def test_load_from_env_custom_addresses():
    """Test loading configuration with custom contract addresses"""
    custom_diamond = "0x1111111111111111111111111111111111111111"
    custom_usdc = "0x2222222222222222222222222222222222222222"

    env = {
        "ARBITRUM_RPC_URL": "https://arb1.arbitrum.io/rpc",
        "ARBITRUM_CHAIN_ID": "42161",
        "GTRADE_DIAMOND_ADDRESS": custom_diamond,
        "USDC_TOKEN_ADDRESS": custom_usdc,
    }

    with patch.dict(os.environ, env, clear=False):
        config = load_chain_config_from_env()

    # Should be checksummed
    from web3 import Web3
    assert config.addresses.diamond == Web3.to_checksum_address(custom_diamond)
    assert config.addresses.usdc == Web3.to_checksum_address(custom_usdc)

    print("✓ Load config from env (custom addresses)")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Unit Test: ChainConfig")
    print("="*60 + "\n")

    test_contract_addresses_checksumming()
    test_chain_config_mainnet()
    test_chain_config_testnet()
    test_chain_config_with_wallet()
    test_load_from_env_mainnet()
    test_load_from_env_with_wallet()
    test_load_from_env_custom_addresses()

    print("\n" + "="*60)
    print("✓ All tests passed")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
