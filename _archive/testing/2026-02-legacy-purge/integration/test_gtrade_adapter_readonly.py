"""
Integration test: GTradeVenueAdapter (read-only with mock)

Tests read-only blockchain integration with mock Web3 provider:
- health_check() with mocked RPC responses
- get_balance() with mocked contract calls
- Start/stop lifecycle
- NO real network calls
"""


from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import asyncio

from web3 import Web3

from infrastructure.venues.gtrade.chain_config import ChainConfig, ContractAddresses
from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter


def create_mock_web3(chain_id=42161):
    """Create a mock AsyncWeb3 instance"""
    mock_w3 = MagicMock()

    # Mock eth.chain_id - each access returns fresh awaitable
    async def mock_chain_id_fn():
        return chain_id
    type(mock_w3.eth).chain_id = PropertyMock(side_effect=lambda: mock_chain_id_fn())

    # Mock eth.block_number - each access returns fresh awaitable
    async def mock_block_number_fn():
        return 123456789
    type(mock_w3.eth).block_number = PropertyMock(side_effect=lambda: mock_block_number_fn())

    # Mock get_code (contract verification)
    mock_w3.eth.get_code = AsyncMock(return_value=b"\x60\x80\x60\x40")

    # Mock get_balance (ETH balance)
    mock_w3.eth.get_balance = AsyncMock(return_value=1_000_000_000_000_000_000)

    # Mock from_wei
    mock_w3.from_wei = Web3.from_wei

    # Mock contract for USDC
    mock_contract = MagicMock()

    # Mock balanceOf function
    mock_balance_of = MagicMock()
    async def mock_balance_of_call():
        # Return 1000 USDC (in smallest units, 6 decimals)
        return 1000_000_000

    mock_balance_of.call = mock_balance_of_call
    mock_contract.functions.balanceOf = MagicMock(return_value=mock_balance_of)

    # Mock decimals function
    mock_decimals = MagicMock()
    async def mock_decimals_call():
        return 6

    mock_decimals.call = mock_decimals_call
    mock_contract.functions.decimals = MagicMock(return_value=mock_decimals)

    # Mock eth.contract
    mock_w3.eth.contract = MagicMock(return_value=mock_contract)

    return mock_w3


async def test_adapter_lifecycle():
    """Test adapter start/stop lifecycle"""
    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    # Mock AsyncWeb3 instantiation
    mock_w3 = create_mock_web3()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3") as mock_web3_class:
        mock_web3_class.return_value = mock_w3

        # Start adapter
        await adapter.start()
        assert adapter._w3 is not None

        # Stop adapter
        await adapter.stop()
        assert adapter._w3 is None

    print("✓ Adapter lifecycle (start/stop)")


async def test_health_check():
    """Test health check with mock RPC"""
    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    mock_w3 = create_mock_web3()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3") as mock_web3_class:
        mock_web3_class.return_value = mock_w3

        await adapter.start()

        # Health check should pass
        healthy = await adapter.health_check()
        assert healthy is True

        await adapter.stop()

    print("✓ Health check (mocked RPC)")


async def test_health_check_chain_id_mismatch():
    """Test health check fails on chain ID mismatch"""
    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,  # Expect mainnet
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    # Create mock with wrong chain ID
    mock_w3 = create_mock_web3(chain_id=1)

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3") as mock_web3_class:
        mock_web3_class.return_value = mock_w3

        await adapter.start()

        # Health check should fail
        healthy = await adapter.health_check()
        assert healthy is False

        await adapter.stop()

    print("✓ Health check fails on chain ID mismatch")


async def test_get_balance_no_wallet():
    """Test get_balance without wallet configured"""
    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
        wallet_private_key=None,  # No wallet
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    mock_w3 = create_mock_web3()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3") as mock_web3_class:
        mock_web3_class.return_value = mock_w3

        await adapter.start()

        # Should return zero balance
        balance = await adapter.get_balance()
        assert balance.usdc == 0.0
        assert balance.native_token == 0.0
        assert balance.available_margin == 0.0
        assert balance.used_margin == 0.0

        await adapter.stop()

    print("✓ Get balance without wallet (returns zero)")


async def test_get_balance_with_wallet():
    """Test get_balance with wallet configured"""
    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
        wallet_private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    mock_w3 = create_mock_web3()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3") as mock_web3_class:
        mock_web3_class.return_value = mock_w3

        await adapter.start()

        # Should return mocked balances
        balance = await adapter.get_balance()

        # ETH: 1 ETH
        # USDC: 1000 USDC
        assert balance.usdc == 1000.0  # USDC balance
        assert balance.native_token == 1.0  # ETH balance
        assert balance.available_margin == 1000.0  # All USDC available
        assert balance.used_margin == 0.0  # No positions

        await adapter.stop()

    print("✓ Get balance with wallet (mocked balances)")


async def test_get_open_positions():
    """Test get_open_positions (stub)"""
    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    mock_w3 = create_mock_web3()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3") as mock_web3_class:
        mock_web3_class.return_value = mock_w3

        await adapter.start()

        # Should return empty list (stub)
        positions = await adapter.get_open_positions()
        assert positions == []

        await adapter.stop()

    print("✓ Get open positions (stub returns empty)")


async def test_write_operations_not_implemented():
    """Test that write operations raise NotImplementedError when disabled"""
    import os

    config = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
        wallet_private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    )

    adapter = GTradeVenueAdapter(chain_config=config, mode="live")

    # Test open_position (disabled by env var)
    with patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "0"}):
        try:
            await adapter.open_position("XAUUSD", True, 100.0, 10.0)
            assert False, "Should raise NotImplementedError"
        except NotImplementedError as e:
            assert "disabled" in str(e).lower()

    # Test close_position (disabled by env var)
    with patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "0"}):
        try:
            await adapter.close_position("pos123")
            assert False, "Should raise NotImplementedError"
        except NotImplementedError as e:
            assert "disabled" in str(e).lower()

    print("✓ Write operations disabled when ENABLE_LIVE_TRADING != 1")


async def test_wallet_helpers():
    """Test wallet helper methods (has_wallet, get_wallet_address, get_account)"""
    # Test with wallet
    config_with_wallet = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
        wallet_private_key="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    )

    adapter = GTradeVenueAdapter(chain_config=config_with_wallet, mode="live")

    # Before start: no wallet yet
    assert not adapter.has_wallet()
    assert adapter.get_wallet_address() is None
    assert adapter.get_account() is None

    # Mock Web3
    mock_w3 = create_mock_web3()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3):
        await adapter.start()

        # After start: wallet available
        assert adapter.has_wallet()
        assert adapter.get_wallet_address() is not None
        assert len(adapter.get_wallet_address()) == 42  # Ethereum address format
        assert adapter.get_account() is not None

        await adapter.stop()

        # After stop: wallet cleared
        assert not adapter.has_wallet()
        assert adapter.get_wallet_address() is None
        assert adapter.get_account() is None

    # Test without wallet
    config_no_wallet = ChainConfig(
        rpc_url="https://mock.rpc",
        chain_id=42161,
        addresses=ContractAddresses(
            diamond="0xFF162c694eAA571f685030649814282eA457f169",
            trading="0xFF162c694eAA571f685030649814282eA457f169",
            usdc="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        ),
        wallet_private_key=None,
    )

    adapter_no_wallet = GTradeVenueAdapter(chain_config=config_no_wallet, mode="live")

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3):
        await adapter_no_wallet.start()

        # No wallet configured
        assert not adapter_no_wallet.has_wallet()
        assert adapter_no_wallet.get_wallet_address() is None
        assert adapter_no_wallet.get_account() is None

        await adapter_no_wallet.stop()

    print("✓ Wallet helpers (has_wallet, get_wallet_address, get_account)")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Integration Test: GTradeVenueAdapter (read-only)")
    print("="*60 + "\n")

    asyncio.run(test_adapter_lifecycle())
    asyncio.run(test_health_check())
    asyncio.run(test_health_check_chain_id_mismatch())
    asyncio.run(test_get_balance_no_wallet())
    asyncio.run(test_get_balance_with_wallet())
    asyncio.run(test_get_open_positions())
    asyncio.run(test_write_operations_not_implemented())
    asyncio.run(test_wallet_helpers())

    print("\n" + "="*60)
    print("✓ All tests passed")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
