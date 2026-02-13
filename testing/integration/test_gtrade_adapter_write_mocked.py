"""
Integration test: GTradeVenueAdapter Write Operations (Mocked)

Tests write operations with mocked TxSender:
- open_position() sends transaction with real ABI-encoded calldata
- Backend confirms position appeared
- PositionRef is populated
- close_position() sends transaction with real ABI-encoded calldata
- NO real network calls

FASE 6B.1.B.2 - Write ops with ABI encoding (placeholder signatures)
"""


from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import asyncio
import os

from application.services.backend_trade_verifier import OpenConfirmResult, CloseConfirmResult
from infrastructure.venues.gtrade.chain_config import ChainConfig, ContractAddresses
from infrastructure.venues.gtrade.config import GTRADE_SYMBOL_TO_PAIR_ID
from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter
from infrastructure.venues.gtrade.tx_sender import TxResult


def create_mock_web3(chain_id=42161):
    """Create a mock AsyncWeb3 instance"""
    mock_w3 = MagicMock()

    # Mock eth.chain_id
    async def mock_chain_id_fn():
        return chain_id
    type(mock_w3.eth).chain_id = PropertyMock(side_effect=lambda: mock_chain_id_fn())

    # Mock eth.block_number
    async def mock_block_number_fn():
        return 123456789
    type(mock_w3.eth).block_number = PropertyMock(side_effect=lambda: mock_block_number_fn())

    # Mock get_code (contract verification)
    mock_w3.eth.get_code = AsyncMock(return_value=b"\\x60\\x80\\x60\\x40")

    # Mock get_balance (ETH balance)
    mock_w3.eth.get_balance = AsyncMock(return_value=1_000_000_000_000_000_000)

    # Mock from_wei
    from web3 import Web3
    mock_w3.from_wei = Web3.from_wei

    # Mock contract
    mock_contract = MagicMock()
    mock_w3.eth.contract = MagicMock(return_value=mock_contract)

    return mock_w3


async def test_open_position_mocked():
    """Test open_position with mocked TxSender"""
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

    # Mock TxSender.send_and_confirm
    fake_tx_hash = "0xabcd1234" * 8  # 64 chars
    fake_tx_result = TxResult(
        tx_hash=fake_tx_hash,
        receipt={"status": 1, "gasUsed": 100_000, "effectiveGasPrice": 1_000_000_000},
        gas_used=100_000,
        effective_gas_price=1_000_000_000,
        status=1,
    )

    # Write-plumbing test: mock symbol mapping so XAUUSD is tradable (independent of mainnet/Sepolia).
    mock_symbol_to_pair = {**GTRADE_SYMBOL_TO_PAIR_ID, "XAUUSD": 0, "EURUSD": 2}

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3), \
         patch("infrastructure.venues.gtrade.gtrade_adapter.TxSender") as mock_tx_sender_class, \
         patch("infrastructure.venues.gtrade.gtrade_adapter.BackendTradeVerifier") as mock_verifier_class, \
         patch("infrastructure.venues.gtrade.gtrade_adapter.GTRADE_SYMBOL_TO_PAIR_ID", mock_symbol_to_pair), \
         patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "1"}):

        # Mock TxSender instance
        mock_sender_instance = AsyncMock()
        mock_sender_instance.send_and_confirm = AsyncMock(return_value=fake_tx_result)
        mock_tx_sender_class.return_value = mock_sender_instance

        # Mock BackendTradeVerifier instance (FASE 6B.1.B.4)
        mock_verifier_instance = AsyncMock()
        mock_verifier_instance.wait_for_open_confirm = AsyncMock(return_value=OpenConfirmResult(
            confirmed=True,
            trade_index=123,
            position_id="0:123",
        ))
        mock_verifier_class.return_value = mock_verifier_instance

        await adapter.start()

        result = await adapter.open_position(
            symbol="XAUUSD",
            is_long=True,
            collateral=1000.0,
            leverage=10.0,
        )

        # Assertions
        assert result.success is True
        assert result.order_id == fake_tx_hash
        assert result.position_id == "0:123"  # Resolved position_id (FASE 6B.1.B.4)
        assert result.executed_size == 10000.0  # collateral * leverage

        # Verify TxSender was created and called
        mock_tx_sender_class.assert_called_once()
        mock_sender_instance.send_and_confirm.assert_called_once()

        # Verify calldata is NOT empty (ABI encoded)
        call_args = mock_sender_instance.send_and_confirm.call_args
        calldata = call_args.kwargs["data"]
        assert len(calldata) > 4, "Calldata should have selector (4 bytes) + parameters"
        assert isinstance(calldata, bytes)
        assert call_args.kwargs["to"] == config.addresses.diamond

        await adapter.stop()

    print("✓ Open position (mocked TxSender, ABI-encoded calldata)")


async def test_close_position_mocked():
    """Test close_position with mocked TxSender"""
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

    # Mock TxSender.send_and_confirm
    fake_tx_hash = "0xef5678" * 10 + "abcd"  # 64 chars
    fake_tx_result = TxResult(
        tx_hash=fake_tx_hash,
        receipt={"status": 1, "gasUsed": 80_000, "effectiveGasPrice": 1_000_000_000},
        gas_used=80_000,
        effective_gas_price=1_000_000_000,
        status=1,
    )

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3), \
         patch("infrastructure.venues.gtrade.gtrade_adapter.TxSender") as mock_tx_sender_class, \
         patch("infrastructure.venues.gtrade.gtrade_adapter.BackendTradeVerifier") as mock_verifier_class, \
         patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "1"}):

        # Mock TxSender instance
        mock_sender_instance = AsyncMock()
        mock_sender_instance.send_and_confirm = AsyncMock(return_value=fake_tx_result)
        mock_tx_sender_class.return_value = mock_sender_instance

        # Mock BackendTradeVerifier instance (FASE 6B.1.B.4)
        mock_verifier_instance = AsyncMock()
        mock_verifier_instance.wait_for_close_confirm = AsyncMock(return_value=CloseConfirmResult(
            confirmed=True,
        ))
        mock_verifier_class.return_value = mock_verifier_instance

        await adapter.start()

        # Call close_position
        success = await adapter.close_position(position_id="0:123")

        # Assertions
        assert success is True

        # Verify TxSender was created and called
        mock_tx_sender_class.assert_called_once()
        mock_sender_instance.send_and_confirm.assert_called_once()

        # Verify calldata is NOT empty (ABI encoded)
        call_args = mock_sender_instance.send_and_confirm.call_args
        calldata = call_args.kwargs["data"]
        assert len(calldata) > 4, "Calldata should have selector (4 bytes) + parameters"
        assert isinstance(calldata, bytes)
        assert call_args.kwargs["to"] == config.addresses.diamond

        await adapter.stop()

    print("✓ Close position (mocked TxSender, ABI-encoded calldata)")


async def test_write_ops_disabled_without_env():
    """Test write operations raise error when ENABLE_LIVE_TRADING != 1"""
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

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3), \
         patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "0"}):

        await adapter.start()

        # Try open_position - should raise NotImplementedError
        try:
            await adapter.open_position("XAUUSD", True, 1000.0, 10.0)
            assert False, "Should raise NotImplementedError"
        except NotImplementedError as e:
            assert "disabled" in str(e).lower()

        # Try close_position - should raise NotImplementedError
        try:
            await adapter.close_position("0:123")
            assert False, "Should raise NotImplementedError"
        except NotImplementedError as e:
            assert "disabled" in str(e).lower()

        await adapter.stop()

    print("✓ Write ops disabled without ENABLE_LIVE_TRADING=1")


async def test_write_ops_require_wallet():
    """Test write operations raise error when wallet not configured"""
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

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3), \
         patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "1"}):

        await adapter.start()

        # Try open_position - should raise ValueError (no wallet)
        try:
            await adapter.open_position("XAUUSD", True, 1000.0, 10.0)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "wallet" in str(e).lower()

        await adapter.stop()

    print("✓ Write ops require wallet configured")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Integration Test: GTradeVenueAdapter Write Ops (ABI Encoded)")
    print("="*60 + "\n")

    asyncio.run(test_open_position_mocked())
    asyncio.run(test_close_position_mocked())
    asyncio.run(test_write_ops_disabled_without_env())
    asyncio.run(test_write_ops_require_wallet())

    print("\n" + "="*60)
    print("✓ All tests passed (4/4)")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
