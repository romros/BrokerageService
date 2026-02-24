"""
Generic Transaction Sender for AsyncWeb3

Handles:
- Nonce management (pending nonce)
- Gas configuration (EIP-1559 + legacy fallback)
- Transaction signing
- Send + wait for receipt
- Error classification
"""


import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.types import TxParams, TxReceipt, Wei

from foundation.logging import get_logger

from .errors import (
    TxError,
    TxRevertError,
    TxTimeoutError,
    TxEstimationError,
    classify_web3_error,
)

logger = get_logger(__name__)


@dataclass
class TxConfig:
    """Transaction configuration"""
    gas_limit: Optional[int] = None  # None = auto-estimate
    max_priority_fee_per_gas: Optional[Wei] = None  # EIP-1559
    max_fee_per_gas: Optional[Wei] = None  # EIP-1559
    gas_price: Optional[Wei] = None  # Legacy
    timeout_seconds: float = 60.0
    poll_interval_seconds: float = 1.0


@dataclass
class TxResult:
    """Transaction result"""
    tx_hash: str
    receipt: TxReceipt
    gas_used: int
    effective_gas_price: int
    status: int  # 1=success, 0=reverted


class TxSender:
    """
    Generic transaction sender for AsyncWeb3

    Handles nonce management, gas config, signing, sending, and error handling.
    """

    def __init__(
        self,
        w3: AsyncWeb3,
        account: LocalAccount,
        default_config: Optional[TxConfig] = None,
    ):
        """
        Args:
            w3: AsyncWeb3 instance
            account: LocalAccount (from Account.from_key)
            default_config: Default tx config (can be overridden per tx)
        """
        self.w3 = w3
        self.account = account
        self.default_config = default_config or TxConfig()

    async def get_pending_nonce(self, address: str) -> int:
        """
        Get pending nonce for address

        Uses 'pending' block to include mempool txs.
        """
        nonce = await self.w3.eth.get_transaction_count(address, "pending")
        logger.debug(f"Pending nonce for {address}: {nonce}")
        return nonce

    async def estimate_gas(self, tx: TxParams) -> int:
        """
        Estimate gas for transaction

        Args:
            tx: Transaction parameters

        Returns:
            Estimated gas limit

        Raises:
            TxEstimationError: If estimation fails (tx would revert)
        """
        try:
            gas = await self.w3.eth.estimate_gas(tx)
            logger.debug(f"Estimated gas: {gas}")
            return gas
        except Exception as e:
            logger.error(f"Gas estimation failed: {e}")
            raise classify_web3_error(e)

    async def get_gas_config(self, config: TxConfig) -> Dict[str, Any]:
        """
        Get gas configuration for transaction

        Tries EIP-1559 first (Arbitrum supports it), fallback to legacy.

        Args:
            config: Transaction config

        Returns:
            Dict with gas fields (maxFeePerGas, maxPriorityFeePerGas OR gasPrice)
        """
        gas_config = {}

        # Try EIP-1559 first
        if config.max_fee_per_gas is not None and config.max_priority_fee_per_gas is not None:
            # User-provided EIP-1559
            gas_config["maxFeePerGas"] = config.max_fee_per_gas
            gas_config["maxPriorityFeePerGas"] = config.max_priority_fee_per_gas
            logger.debug(f"Using user-provided EIP-1559: maxFee={config.max_fee_per_gas}, maxPriority={config.max_priority_fee_per_gas}")
        elif config.gas_price is not None:
            # User-provided legacy
            gas_config["gasPrice"] = config.gas_price
            logger.debug(f"Using user-provided legacy gasPrice={config.gas_price}")
        else:
            # Auto-detect: try EIP-1559
            try:
                base_fee = await self.w3.eth.gas_price  # Simple approach for now
                max_priority_fee = Wei(int(base_fee * 0.1))  # 10% tip
                max_fee = Wei(int(base_fee * 1.5))  # 50% buffer

                gas_config["maxFeePerGas"] = max_fee
                gas_config["maxPriorityFeePerGas"] = max_priority_fee
                logger.debug(f"Auto EIP-1559: maxFee={max_fee}, maxPriority={max_priority_fee}")
            except Exception as e:
                # Fallback to legacy
                logger.warning(f"EIP-1559 failed, falling back to legacy: {e}")
                gas_price = await self.w3.eth.gas_price
                gas_config["gasPrice"] = gas_price
                logger.debug(f"Auto legacy gasPrice={gas_price}")

        return gas_config

    async def build_tx(
        self,
        to: str,
        data: bytes,
        value: Wei = Wei(0),
        config: Optional[TxConfig] = None,
    ) -> TxParams:
        """
        Build transaction with nonce + gas config

        Args:
            to: Contract address
            data: Calldata
            value: ETH value to send
            config: Override default config

        Returns:
            TxParams ready to sign
        """
        cfg = config or self.default_config

        # Get nonce
        nonce = await self.get_pending_nonce(self.account.address)

        # Build base tx
        tx: TxParams = {
            "from": self.account.address,
            "to": to,
            "data": data,
            "value": value,
            "nonce": nonce,
            "chainId": await self.w3.eth.chain_id,
        }

        # Add gas config
        gas_config = await self.get_gas_config(cfg)
        tx.update(gas_config)

        # Estimate gas if not provided
        if cfg.gas_limit is None:
            gas_limit = await self.estimate_gas(tx)
            # Add 20% buffer
            tx["gas"] = int(gas_limit * 1.2)
        else:
            tx["gas"] = cfg.gas_limit

        logger.info(f"Built tx: to={to}, gas={tx['gas']}, nonce={nonce}")
        return tx

    def sign_tx(self, tx: TxParams) -> bytes:
        """
        Sign transaction

        Args:
            tx: Transaction parameters

        Returns:
            Signed raw transaction bytes
        """
        signed = self.account.sign_transaction(tx)
        logger.debug(f"Signed tx: {signed.hash.hex()}")
        return signed.raw_transaction

    async def send_raw_tx(self, raw_tx: bytes) -> str:
        """
        Send signed raw transaction

        Args:
            raw_tx: Signed raw transaction

        Returns:
            Transaction hash (hex string)

        Raises:
            TxError: If send fails
        """
        try:
            tx_hash = await self.w3.eth.send_raw_transaction(raw_tx)
            tx_hash_hex = tx_hash.hex()
            logger.info(f"Sent tx: {tx_hash_hex}")
            return tx_hash_hex
        except Exception as e:
            logger.error(f"Failed to send tx: {e}")
            raise classify_web3_error(e)

    async def wait_receipt(
        self,
        tx_hash: str,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> TxReceipt:
        """
        Wait for transaction receipt

        Args:
            tx_hash: Transaction hash
            timeout: Max wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Transaction receipt

        Raises:
            TxTimeoutError: If receipt not received within timeout
            TxRevertError: If transaction reverted (status=0)
        """
        start = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                logger.error(f"Timeout waiting for tx {tx_hash}")
                raise TxTimeoutError(f"Timeout waiting for tx {tx_hash}", tx_hash)

            try:
                receipt = await self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    # Check status
                    if receipt["status"] == 0:
                        logger.error(f"Tx reverted: {tx_hash}")
                        raise TxRevertError(
                            f"Transaction reverted: {tx_hash}",
                            tx_hash,
                            revert_reason=None,  # TODO: Extract revert reason via eth_call
                        )

                    logger.info(f"Tx confirmed: {tx_hash}, gas_used={receipt['gasUsed']}")
                    return receipt
            except TxRevertError:
                raise
            except Exception as e:
                # Ignore errors during polling (tx might not be mined yet)
                logger.debug(f"Polling error (ignoring): {e}")

            await asyncio.sleep(poll_interval)

    async def send_and_confirm(
        self,
        to: str,
        data: bytes,
        value: Wei = Wei(0),
        config: Optional[TxConfig] = None,
    ) -> TxResult:
        """
        Build, sign, send, and wait for transaction

        Args:
            to: Contract address
            data: Calldata
            value: ETH value
            config: Override default config

        Returns:
            TxResult with receipt

        Raises:
            TxError: If any step fails
        """
        cfg = config or self.default_config

        # Build + estimate gas
        tx = await self.build_tx(to, data, value, cfg)

        # Sign
        raw_tx = self.sign_tx(tx)

        # Send
        tx_hash = await self.send_raw_tx(raw_tx)

        # Wait
        receipt = await self.wait_receipt(
            tx_hash,
            timeout=cfg.timeout_seconds,
            poll_interval=cfg.poll_interval_seconds,
        )

        return TxResult(
            tx_hash=tx_hash,
            receipt=receipt,
            gas_used=receipt["gasUsed"],
            effective_gas_price=receipt["effectiveGasPrice"],
            status=receipt["status"],
        )
