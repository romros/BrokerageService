"""
gTrade Backend Response Mappers

Maps backend API responses → domain models.

Philosophy:
- Tolerant to missing fields (log warnings, use defaults)
- Ignore unexpected fields
- Store raw data in venue_metadata for debugging

References:
- https://docs.gains.trade/developer/integrators/backend
"""


from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from .config import GTRADE_PAIR_ID_TO_SYMBOL

from domain.models import Position
from foundation.config.constants import CANONICAL_TIMEZONE
from foundation.logging import get_logger


logger = get_logger(__name__)


def map_open_trade_to_position(trade: dict, wallet_address: str) -> Optional[Position]:
    """
    Map single open trade from backend → Position

    Args:
        trade: Raw trade dict from backend
        wallet_address: Trader wallet address

    Returns:
        Position object or None if mapping fails

    Tolerant to:
    - Missing fields (log warning, use defaults)
    - Unknown pair IDs (log error, return None)
    """
    try:
        # Extract required fields
        pair_index = trade.get("pairIndex")
        if pair_index is None:
            logger.warning(f"Missing pairIndex in trade: {trade}")
            return None

        # Map pair ID → symbol
        symbol = GTRADE_PAIR_ID_TO_SYMBOL.get(pair_index)
        if symbol is None:
            logger.error(f"Unknown pairIndex {pair_index}, skipping trade")
            return None

        # Trade index (unique per trader)
        trade_index = trade.get("index", 0)

        # Buy (true) = LONG, Buy (false) = SHORT
        is_long = trade.get("buy", True)

        # Entry price (openPrice)
        open_price = float(trade.get("openPrice", 0.0))
        if open_price <= 0:
            logger.warning(f"Invalid openPrice {open_price} for trade {pair_index}:{trade_index}")
            return None

        # Collateral (initial margin in USDC)
        collateral = float(trade.get("initialPosToken", 0.0))
        if collateral <= 0:
            logger.warning(f"Invalid collateral {collateral} for trade {pair_index}:{trade_index}")
            return None

        # Leverage
        leverage = float(trade.get("leverage", 1.0))
        if leverage <= 0:
            leverage = 1.0
            logger.warning(f"Invalid leverage, using 1.0 for trade {pair_index}:{trade_index}")

        # Position size (notional) = collateral * leverage
        notional = collateral * leverage

        # Stop loss / Take profit (optional)
        sl_price = trade.get("sl")
        tp_price = trade.get("tp")
        if sl_price is not None:
            sl_price = float(sl_price)
            if sl_price <= 0:
                sl_price = None
        if tp_price is not None:
            tp_price = float(tp_price)
            if tp_price <= 0:
                tp_price = None

        # Opened timestamp (if available)
        # Backend may provide timestamp_ms or similar
        open_time = None
        if "openedAt" in trade:
            try:
                # Assume Unix timestamp in seconds
                ts = float(trade["openedAt"])
                open_time = datetime.fromtimestamp(ts, tz=timezone.utc)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid openedAt timestamp: {e}")

        # Current price (we don't have it from backend, use open_price as placeholder)
        current_price = open_price

        # Create Position (using domain model structure)
        position = Position(
            pair_id=pair_index,
            trade_index=trade_index,
            symbol=symbol,
            is_long=is_long,
            collateral=collateral,
            leverage=leverage,
            open_price=open_price,
            current_price=current_price,  # Placeholder
            sl_price=sl_price,
            tp_price=tp_price,
            open_time=open_time,
            notional=notional,
            wallet_address=wallet_address,  # Set wallet for PositionRef
        )

        logger.debug(f"Mapped position: {position.position_id} ({symbol} {position.side}, notional={notional:.2f})")
        return position

    except Exception as e:
        logger.error(f"Error mapping trade to position: {e}, trade={trade}")
        return None


def map_open_trades_response(payload: Any, wallet_address: str) -> List[Position]:
    """
    Map backend open-trades response → List[Position]

    Args:
        payload: Backend response (list or dict)
        wallet_address: Trader wallet address

    Returns:
        List of Position objects (empty if no trades)

    Tolerant to:
    - Empty responses
    - Invalid trade entries (skip with warning)
    """
    positions = []

    # Handle different response formats
    if isinstance(payload, list):
        # Direct list of trades
        trades = payload
    elif isinstance(payload, dict):
        # Nested in "trades" or "openTrades" key
        trades = payload.get("trades") or payload.get("openTrades") or []
    else:
        logger.warning(f"Unexpected payload type: {type(payload)}")
        return positions

    logger.info(f"Mapping {len(trades)} open trades for {wallet_address}")

    for trade in trades:
        position = map_open_trade_to_position(trade, wallet_address)
        if position is not None:
            positions.append(position)

    logger.info(f"Mapped {len(positions)}/{len(trades)} positions successfully")
    return positions
