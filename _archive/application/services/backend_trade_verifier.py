"""
Backend Trade Verifier - Post-transaction confirmation via backend polling

Verifies that blockchain transactions are reflected in the gTrade backend API.
Converts "pending:<txhash>" positions to resolved "pair_id:trade_index" after confirmation.

FASE 6B.1.B.4 - Backend Verification Loop
"""


from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, List
import asyncio

from domain.models.position import Position
from foundation.logging import get_logger
from infrastructure.venues.gtrade.backend_client import GTradeBackendClient


logger = get_logger(__name__)


# ============================================================================
# Configuration
# ============================================================================

# Default timeout for backend confirmation (seconds)
DEFAULT_CONFIRM_TIMEOUT_SECONDS = 60.0

# Default polling interval (seconds)
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


# ============================================================================
# Errors
# ============================================================================

class BackendConfirmationError(Exception):
    """Base error for backend confirmation failures"""
    pass


class BackendConfirmationTimeout(BackendConfirmationError):
    """Backend confirmation timed out"""
    pass


class BackendTradeMismatch(BackendConfirmationError):
    """Backend returned trade but with unexpected data"""
    pass


# ============================================================================
# Result Types
# ============================================================================

@dataclass
class OpenConfirmResult:
    """Result of open position confirmation"""
    confirmed: bool
    trade_index: Optional[int] = None
    position_id: Optional[str] = None  # "pair_id:trade_index"
    backend_position: Optional[Position] = None
    error: Optional[str] = None


@dataclass
class CloseConfirmResult:
    """Result of close position confirmation"""
    confirmed: bool
    error: Optional[str] = None


# ============================================================================
# Backend Trade Verifier
# ============================================================================

class BackendTradeVerifier:
    """
    Verifies blockchain transactions via backend polling

    Converts "pending:<txhash>" to resolved "pair_id:trade_index" after confirmation.
    """

    def __init__(
        self,
        backend_client: GTradeBackendClient,
        timeout_seconds: float = DEFAULT_CONFIRM_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        sleep_fn: Optional[Callable[[float], asyncio.Future]] = None,
    ):
        """
        Initialize verifier

        Args:
            backend_client: Backend API client
            timeout_seconds: Max time to wait for confirmation
            poll_interval_seconds: Time between polls
            sleep_fn: Sleep function (for testing with fake clock)
        """
        self._client = backend_client
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._sleep_fn = sleep_fn or asyncio.sleep

        logger.info(
            f"BackendTradeVerifier initialized: timeout={timeout_seconds}s, "
            f"poll_interval={poll_interval_seconds}s"
        )

    async def wait_for_open_confirm(
        self,
        wallet_address: str,
        pair_id: int,
        tx_hash: str,
    ) -> OpenConfirmResult:
        """
        Wait for backend to confirm new open position

        Polls /open-trades/<address> until a new trade appears for the given pair_id.

        Args:
            wallet_address: Trader wallet address
            pair_id: Trading pair ID (0=XAUUSD, 1=EURUSD, etc.)
            tx_hash: Transaction hash (for logging)

        Returns:
            OpenConfirmResult with trade_index if confirmed, error if timeout

        Note:
            This assumes the trade didn't exist before. If you need to handle
            "update existing trade", pass a baseline list of existing trades.
        """
        logger.info(
            f"Waiting for open confirm: wallet={wallet_address[:8]}..., "
            f"pair_id={pair_id}, tx_hash={tx_hash[:10]}..."
        )

        start_time = asyncio.get_event_loop().time()
        poll_count = 0

        # Get baseline (trades before tx)
        baseline_trades = await self._client.get_open_trades(wallet_address)
        baseline_indices = {t.trade_index for t in baseline_trades if t.pair_id == pair_id}

        logger.debug(f"Baseline trades for pair_id={pair_id}: {baseline_indices}")

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self._timeout:
                error_msg = (
                    f"Backend confirmation timeout after {elapsed:.1f}s "
                    f"(tx_hash={tx_hash[:10]}..., pair_id={pair_id})"
                )
                logger.error(error_msg)
                return OpenConfirmResult(
                    confirmed=False,
                    error=f"BACKEND_TIMEOUT (after {elapsed:.1f}s)"
                )

            # Poll backend
            poll_count += 1
            current_trades = await self._client.get_open_trades(wallet_address)
            current_pair_trades = [t for t in current_trades if t.pair_id == pair_id]

            logger.debug(
                f"Poll {poll_count}: found {len(current_pair_trades)} trades "
                f"for pair_id={pair_id} (elapsed={elapsed:.1f}s)"
            )

            # Check for new trade (not in baseline)
            for trade in current_pair_trades:
                if trade.trade_index not in baseline_indices:
                    # Found new trade!
                    position_id = f"{trade.pair_id}:{trade.trade_index}"
                    logger.info(
                        f"✅ Backend confirmed open: position_id={position_id}, "
                        f"trade_index={trade.trade_index} (elapsed={elapsed:.1f}s, polls={poll_count})"
                    )
                    return OpenConfirmResult(
                        confirmed=True,
                        trade_index=trade.trade_index,
                        position_id=position_id,
                        backend_position=trade,
                    )

            # Sleep before next poll
            await self._sleep_fn(self._poll_interval)

    async def wait_for_close_confirm(
        self,
        wallet_address: str,
        pair_id: int,
        trade_index: int,
        tx_hash: str,
    ) -> CloseConfirmResult:
        """
        Wait for backend to confirm position closed (disappeared from API)

        Polls /open-trades/<address> until the trade is no longer present.

        Args:
            wallet_address: Trader wallet address
            pair_id: Trading pair ID
            trade_index: Trade index to confirm closed
            tx_hash: Transaction hash (for logging)

        Returns:
            CloseConfirmResult with confirmed=True if disappeared, error if timeout
        """
        logger.info(
            f"Waiting for close confirm: wallet={wallet_address[:8]}..., "
            f"position={pair_id}:{trade_index}, tx_hash={tx_hash[:10]}..."
        )

        start_time = asyncio.get_event_loop().time()
        poll_count = 0

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self._timeout:
                error_msg = (
                    f"Backend close confirmation timeout after {elapsed:.1f}s "
                    f"(tx_hash={tx_hash[:10]}..., position={pair_id}:{trade_index})"
                )
                logger.error(error_msg)
                return CloseConfirmResult(
                    confirmed=False,
                    error=f"BACKEND_TIMEOUT (after {elapsed:.1f}s)"
                )

            # Poll backend
            poll_count += 1
            current_trades = await self._client.get_open_trades(wallet_address)

            # Check if position still exists
            position_exists = any(
                t.pair_id == pair_id and t.trade_index == trade_index
                for t in current_trades
            )

            logger.debug(
                f"Poll {poll_count}: position {pair_id}:{trade_index} exists={position_exists} "
                f"(elapsed={elapsed:.1f}s)"
            )

            if not position_exists:
                # Position disappeared = closed confirmed!
                logger.info(
                    f"✅ Backend confirmed close: position={pair_id}:{trade_index} "
                    f"(elapsed={elapsed:.1f}s, polls={poll_count})"
                )
                return CloseConfirmResult(confirmed=True)

            # Sleep before next poll
            await self._sleep_fn(self._poll_interval)
