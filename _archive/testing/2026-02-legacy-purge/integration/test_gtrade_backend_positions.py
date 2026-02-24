"""
Integration test: GTradeVenueAdapter - Backend Open Positions (FASE 6B.1.A)

Tests backend API integration for open positions:
- Mock backend client responses
- Map backend trades → Position objects
- Handle empty responses
- Tolerant to malformed data
- NO real network calls
"""


from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from infrastructure.venues.gtrade.backend_client import GTradeBackendClient
from infrastructure.venues.gtrade.chain_config import ChainConfig, ContractAddresses
from infrastructure.venues.gtrade.config import GTRADE_PAIR_ID_TO_SYMBOL
from infrastructure.venues.gtrade.gtrade_adapter import GTradeVenueAdapter


def create_mock_backend_client():
    """Create a mock backend client"""
    mock_client = AsyncMock(spec=GTradeBackendClient)
    return mock_client


async def test_get_open_positions_empty():
    """Test get_open_positions with no positions"""
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

    mock_backend = create_mock_backend_client()
    mock_backend.get_open_trades.return_value = []  # Empty response

    adapter = GTradeVenueAdapter(
        chain_config=config,
        backend_client=mock_backend,
        mode="live"
    )

    # Mock Web3: adapter does await self._w3.eth.chain_id — must be a real awaitable
    async def _chain_id():
        return 42161
    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = _chain_id()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3):
        await adapter.start()

        positions = await adapter.get_open_positions()
        assert positions == []

        await adapter.stop()

    print("✓ Get open positions (empty)")


async def test_get_open_positions_two_trades():
    """Test get_open_positions with 2 trades (XAUUSD long + EURUSD short)"""
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

    # pairIndex 0 and 2: symbols come from config (mainnet: XAUUSD/EURUSD, Sepolia: BTCUSD/LINKUSD)
    symbol0 = GTRADE_PAIR_ID_TO_SYMBOL.get(0)
    symbol2 = GTRADE_PAIR_ID_TO_SYMBOL.get(2)
    assert symbol0 and symbol2, "pairId 0 and 2 must be in GTRADE_PAIR_ID_TO_SYMBOL"

    mock_response = [
        {
            "pairIndex": 0,
            "index": 1,
            "buy": True,  # LONG
            "openPrice": "2700.50",
            "initialPosToken": "1000.0",
            "leverage": "10.0",
            "sl": "2650.0",
            "tp": "2800.0",
            "openedAt": 1707500000,
        },
        {
            "pairIndex": 2,
            "index": 2,
            "buy": False,  # SHORT
            "openPrice": "1.0850",
            "initialPosToken": "500.0",
            "leverage": "20.0",
            "sl": "1.0900",
            "tp": "1.0800",
            "openedAt": 1707500100,
        },
    ]

    mock_backend = create_mock_backend_client()
    mock_backend.get_open_trades.return_value = mock_response

    adapter = GTradeVenueAdapter(
        chain_config=config,
        backend_client=mock_backend,
        mode="live"
    )

    async def _chain_id():
        return 42161
    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = _chain_id()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3):
        await adapter.start()

        positions = await adapter.get_open_positions()

        assert len(positions) == 2

        # First position (pair_id 0)
        pos1 = positions[0]
        assert pos1.pair_id == 0
        assert pos1.symbol == symbol0
        assert pos1.side == "LONG"
        assert pos1.is_long is True
        assert pos1.open_price == 2700.50
        assert pos1.collateral == 1000.0
        assert pos1.leverage == 10.0
        assert pos1.notional == 10000.0
        assert pos1.sl_price == 2650.0
        assert pos1.tp_price == 2800.0
        assert pos1.trade_index == 1
        assert pos1.position_id == "0:1"
        assert pos1.wallet_address == "0x1Be31A94361a391bBaFB2a4CCd704F57dc04d4bb"
        ref1 = pos1.get_ref()
        assert ref1 is not None
        assert ref1.wallet_address == pos1.wallet_address
        assert ref1.pair_id == 0
        assert ref1.trade_index == 1

        # Second position (pair_id 2)
        pos2 = positions[1]
        assert pos2.pair_id == 2
        assert pos2.symbol == symbol2
        assert pos2.side == "SHORT"
        assert pos2.is_long is False
        assert pos2.open_price == 1.0850
        assert pos2.collateral == 500.0
        assert pos2.leverage == 20.0
        assert pos2.notional == 10000.0
        assert pos2.sl_price == 1.0900
        assert pos2.tp_price == 1.0800
        assert pos2.trade_index == 2
        assert pos2.position_id == "2:2"
        assert pos2.wallet_address == "0x1Be31A94361a391bBaFB2a4CCd704F57dc04d4bb"
        ref2 = pos2.get_ref()
        assert ref2 is not None
        assert ref2.wallet_address == pos2.wallet_address
        assert ref2.pair_id == 2
        assert ref2.trade_index == 2

        await adapter.stop()

    print("✓ Get open positions (2 trades: pair_id 0 long + pair_id 2 short)")


async def test_get_open_positions_malformed_trade():
    """Test get_open_positions with malformed trade (should skip gracefully)"""
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

    # 1 valid trade (pairIndex 0) + 1 invalid (missing pairIndex)
    mock_response = [
        {
            "pairIndex": 0,
            "index": 1,
            "buy": True,
            "openPrice": "2700.50",
            "initialPosToken": "1000.0",
            "leverage": "10.0",
        },
        {
            "index": 2,
            "buy": True,
            "openPrice": "1.0850",
        },
    ]

    mock_backend = create_mock_backend_client()
    mock_backend.get_open_trades.return_value = mock_response

    adapter = GTradeVenueAdapter(
        chain_config=config,
        backend_client=mock_backend,
        mode="live"
    )

    async def _chain_id():
        return 42161
    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = _chain_id()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3):
        await adapter.start()

        positions = await adapter.get_open_positions()
        assert len(positions) == 1
        assert positions[0].pair_id == 0
        assert positions[0].symbol == GTRADE_PAIR_ID_TO_SYMBOL[0]

        await adapter.stop()

    print("✓ Get open positions (malformed trade skipped gracefully)")


async def test_get_open_positions_no_wallet():
    """Test get_open_positions without wallet configured"""
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

    mock_backend = create_mock_backend_client()

    adapter = GTradeVenueAdapter(
        chain_config=config,
        backend_client=mock_backend,
        mode="live"
    )

    async def _chain_id():
        return 42161
    mock_w3 = MagicMock()
    mock_w3.eth.chain_id = _chain_id()

    with patch("infrastructure.venues.gtrade.gtrade_adapter.AsyncWeb3", return_value=mock_w3):
        await adapter.start()

        positions = await adapter.get_open_positions()
        assert positions == []

        mock_backend.get_open_trades.assert_not_called()

        await adapter.stop()

    print("✓ Get open positions (no wallet, returns empty)")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Integration Test: gTrade Backend Open Positions")
    print("="*60 + "\n")

    asyncio.run(test_get_open_positions_empty())
    asyncio.run(test_get_open_positions_two_trades())
    asyncio.run(test_get_open_positions_malformed_trade())
    asyncio.run(test_get_open_positions_no_wallet())

    print("\n" + "="*60)
    print("✓ All tests passed")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
