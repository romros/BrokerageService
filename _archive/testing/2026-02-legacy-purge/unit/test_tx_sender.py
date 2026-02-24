"""
Unit test: TxSender - Generic transaction plumbing

Tests transaction building, signing, sending, and error handling:
- Nonce management (pending)
- Gas estimation
- EIP-1559 + legacy fallback
- Sign + send + wait receipt
- Error classification (revert, timeout, nonce too low, etc.)
- NO real network calls (all mocked)
"""


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from eth_account import Account
from web3.types import Wei

from infrastructure.venues.gtrade.errors import (
    TxRevertError,
    TxTimeoutError,
    TxNonceTooLowError,
    TxUnderpricedError,
    TxInsufficientFundsError,
    TxEstimationError,
)
from infrastructure.venues.gtrade.tx_sender import TxSender, TxConfig, TxResult


def create_awaitable_property(value):
    """Create an awaitable property that returns a value"""
    class AwaitableProperty:
        def __await__(self):
            async def get_value():
                return value
            return get_value().__await__()
    return AwaitableProperty()


def create_mock_w3():
    """Create a mock AsyncWeb3 instance"""
    mock = AsyncMock()
    mock.eth = AsyncMock()
    # chain_id is an awaitable property
    mock.eth.chain_id = create_awaitable_property(42161)
    return mock


def create_mock_account():
    """Create a mock LocalAccount"""
    # Generate a random account for testing
    account = Account.create()
    return account


async def test_get_pending_nonce():
    """Test get_pending_nonce"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.get_transaction_count = AsyncMock(return_value=42)

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    nonce = await sender.get_pending_nonce(account.address)

    assert nonce == 42
    mock_w3.eth.get_transaction_count.assert_called_once_with(account.address, "pending")

    print("✓ Get pending nonce")


async def test_estimate_gas_success():
    """Test estimate_gas success"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.estimate_gas = AsyncMock(return_value=100_000)

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    tx = {"to": "0x1234", "data": b""}
    gas = await sender.estimate_gas(tx)

    assert gas == 100_000
    mock_w3.eth.estimate_gas.assert_called_once_with(tx)

    print("✓ Estimate gas success")


async def test_estimate_gas_failure():
    """Test estimate_gas failure (tx would revert)"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.estimate_gas = AsyncMock(side_effect=Exception("execution reverted"))

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    tx = {"to": "0x1234", "data": b""}

    try:
        await sender.estimate_gas(tx)
        assert False, "Should have raised TxEstimationError"
    except TxEstimationError as e:
        assert "execution reverted" in str(e)

    print("✓ Estimate gas failure (reverted)")


async def test_get_gas_config_eip1559():
    """Test get_gas_config with EIP-1559"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.gas_price = create_awaitable_property(Wei(1_000_000_000))  # 1 gwei

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    config = TxConfig()
    gas_config = await sender.get_gas_config(config)

    # Should auto-detect EIP-1559
    assert "maxFeePerGas" in gas_config
    assert "maxPriorityFeePerGas" in gas_config
    assert gas_config["maxFeePerGas"] == Wei(1_500_000_000)  # 1.5x base
    assert gas_config["maxPriorityFeePerGas"] == Wei(100_000_000)  # 10% tip

    print("✓ Get gas config (EIP-1559 auto)")


async def test_get_gas_config_legacy():
    """Test get_gas_config with legacy gas price"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.gas_price = create_awaitable_property(Wei(2_000_000_000))  # 2 gwei

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    config = TxConfig(gas_price=Wei(3_000_000_000))  # User-provided legacy
    gas_config = await sender.get_gas_config(config)

    # Should use user-provided legacy
    assert "gasPrice" in gas_config
    assert gas_config["gasPrice"] == Wei(3_000_000_000)

    print("✓ Get gas config (legacy user-provided)")


async def test_build_tx_success():
    """Test build_tx success"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.get_transaction_count = AsyncMock(return_value=5)
    mock_w3.eth.gas_price = create_awaitable_property(Wei(1_000_000_000))
    mock_w3.eth.estimate_gas = AsyncMock(return_value=100_000)

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    tx = await sender.build_tx(
        to="0x1234567890123456789012345678901234567890",
        data=b"\x12\x34",
        value=Wei(0),
    )

    assert tx["to"] == "0x1234567890123456789012345678901234567890"
    assert tx["data"] == b"\x12\x34"
    assert tx["value"] == Wei(0)
    assert tx["nonce"] == 5
    assert tx["chainId"] == 42161
    assert tx["gas"] == 120_000  # 100k * 1.2 buffer
    assert "maxFeePerGas" in tx or "gasPrice" in tx

    print("✓ Build tx success")


async def test_sign_tx():
    """Test sign_tx"""
    mock_w3 = create_mock_w3()
    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    tx = {
        "from": account.address,
        "to": "0x1234567890123456789012345678901234567890",
        "data": b"",
        "value": Wei(0),
        "nonce": 0,
        "chainId": 42161,
        "gas": 100_000,
        "gasPrice": Wei(1_000_000_000),
    }

    raw_tx = sender.sign_tx(tx)

    assert isinstance(raw_tx, bytes)
    assert len(raw_tx) > 0

    print("✓ Sign tx")


async def test_send_raw_tx_success():
    """Test send_raw_tx success"""
    mock_w3 = create_mock_w3()
    mock_tx_hash = b"\x12\x34" * 16  # 32 bytes
    mock_w3.eth.send_raw_transaction = AsyncMock(return_value=mock_tx_hash)

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    raw_tx = b"\xaa\xbb\xcc"
    tx_hash = await sender.send_raw_tx(raw_tx)

    assert tx_hash == mock_tx_hash.hex()
    mock_w3.eth.send_raw_transaction.assert_called_once_with(raw_tx)

    print("✓ Send raw tx success")


async def test_send_raw_tx_nonce_too_low():
    """Test send_raw_tx with nonce too low"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.send_raw_transaction = AsyncMock(
        side_effect=Exception("nonce too low")
    )

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    raw_tx = b"\xaa\xbb\xcc"

    try:
        await sender.send_raw_tx(raw_tx)
        assert False, "Should have raised TxNonceTooLowError"
    except TxNonceTooLowError as e:
        assert "nonce too low" in str(e).lower()

    print("✓ Send raw tx (nonce too low)")


async def test_send_raw_tx_underpriced():
    """Test send_raw_tx with underpriced gas"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.send_raw_transaction = AsyncMock(
        side_effect=Exception("replacement transaction underpriced")
    )

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    raw_tx = b"\xaa\xbb\xcc"

    try:
        await sender.send_raw_tx(raw_tx)
        assert False, "Should have raised TxUnderpricedError"
    except TxUnderpricedError as e:
        assert "underpriced" in str(e).lower()

    print("✓ Send raw tx (underpriced)")


async def test_send_raw_tx_insufficient_funds():
    """Test send_raw_tx with insufficient funds"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.send_raw_transaction = AsyncMock(
        side_effect=Exception("insufficient funds for gas * price + value")
    )

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    raw_tx = b"\xaa\xbb\xcc"

    try:
        await sender.send_raw_tx(raw_tx)
        assert False, "Should have raised TxInsufficientFundsError"
    except TxInsufficientFundsError as e:
        assert "insufficient funds" in str(e).lower()

    print("✓ Send raw tx (insufficient funds)")


async def test_wait_receipt_success():
    """Test wait_receipt success"""
    mock_w3 = create_mock_w3()
    mock_receipt = {
        "status": 1,
        "gasUsed": 100_000,
        "effectiveGasPrice": 1_000_000_000,
    }
    mock_w3.eth.get_transaction_receipt = AsyncMock(return_value=mock_receipt)

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    receipt = await sender.wait_receipt("0x1234", timeout=5.0, poll_interval=0.1)

    assert receipt == mock_receipt
    assert receipt["status"] == 1

    print("✓ Wait receipt success")


async def test_wait_receipt_reverted():
    """Test wait_receipt with reverted tx"""
    mock_w3 = create_mock_w3()
    mock_receipt = {
        "status": 0,  # Reverted
        "gasUsed": 100_000,
        "effectiveGasPrice": 1_000_000_000,
    }
    mock_w3.eth.get_transaction_receipt = AsyncMock(return_value=mock_receipt)

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    try:
        await sender.wait_receipt("0x1234", timeout=5.0, poll_interval=0.1)
        assert False, "Should have raised TxRevertError"
    except TxRevertError as e:
        assert "reverted" in str(e).lower()
        assert e.tx_hash == "0x1234"

    print("✓ Wait receipt (reverted)")


async def test_wait_receipt_timeout():
    """Test wait_receipt with timeout"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.get_transaction_receipt = AsyncMock(return_value=None)  # Not mined yet

    account = create_mock_account()
    sender = TxSender(mock_w3, account)

    try:
        await sender.wait_receipt("0x1234", timeout=0.5, poll_interval=0.1)
        assert False, "Should have raised TxTimeoutError"
    except TxTimeoutError as e:
        assert "timeout" in str(e).lower()
        assert e.tx_hash == "0x1234"

    print("✓ Wait receipt (timeout)")


async def test_send_and_confirm_success():
    """Test send_and_confirm complete flow"""
    mock_w3 = create_mock_w3()
    mock_w3.eth.get_transaction_count = AsyncMock(return_value=10)
    mock_w3.eth.gas_price = create_awaitable_property(Wei(1_000_000_000))
    mock_w3.eth.estimate_gas = AsyncMock(return_value=100_000)
    mock_w3.eth.send_raw_transaction = AsyncMock(return_value=b"\x12\x34" * 16)
    mock_w3.eth.get_transaction_receipt = AsyncMock(
        return_value={
            "status": 1,
            "gasUsed": 100_000,
            "effectiveGasPrice": 1_000_000_000,
        }
    )

    account = create_mock_account()
    sender = TxSender(mock_w3, account, TxConfig(timeout_seconds=5.0, poll_interval_seconds=0.1))

    result = await sender.send_and_confirm(
        to="0x1234567890123456789012345678901234567890",
        data=b"\xaa\xbb",
        value=Wei(0),
    )

    assert isinstance(result, TxResult)
    assert result.status == 1
    assert result.gas_used == 100_000
    assert result.effective_gas_price == 1_000_000_000
    assert len(result.tx_hash) == 64  # Hex string

    print("✓ Send and confirm (complete flow)")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Unit Test: TxSender - Transaction Plumbing")
    print("="*60 + "\n")

    asyncio.run(test_get_pending_nonce())
    asyncio.run(test_estimate_gas_success())
    asyncio.run(test_estimate_gas_failure())
    asyncio.run(test_get_gas_config_eip1559())
    asyncio.run(test_get_gas_config_legacy())
    asyncio.run(test_build_tx_success())
    asyncio.run(test_sign_tx())
    asyncio.run(test_send_raw_tx_success())
    asyncio.run(test_send_raw_tx_nonce_too_low())
    asyncio.run(test_send_raw_tx_underpriced())
    asyncio.run(test_send_raw_tx_insufficient_funds())
    asyncio.run(test_wait_receipt_success())
    asyncio.run(test_wait_receipt_reverted())
    asyncio.run(test_wait_receipt_timeout())
    asyncio.run(test_send_and_confirm_success())

    print("\n" + "="*60)
    print("✓ All tests passed (15/15)")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
