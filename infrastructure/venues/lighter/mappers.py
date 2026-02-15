"""
Lighter Market Data Mappers

Maps Lighter SDK responses → domain models.

Functions:
- normalize_symbol(): Canonicalize symbol format ("ETH-USDC" → "ETH")
- map_order_books_to_trading_pairs(): OrderBook list → TradingPair list
- map_order_book_orders_to_price_data(): OrderBookOrders → PriceData

References:
- lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Market Data Investigation
"""


from datetime import datetime, timezone
from typing import Any, List, Callable, Optional

from domain.errors import MarketNotFoundError, NoLiquidityError
from domain.models import TradingPair, PriceData, Position, Balance
from foundation.logging import get_logger

logger = get_logger(__name__)


def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol to Lighter format

    Accepts:
    - "ETH-USDC" → "ETH"
    - "ETH" → "ETH"
    - "eth" → "ETH" (uppercase)

    Args:
        symbol: Input symbol (may include quote or be base only)

    Returns:
        Normalized base symbol (uppercase, no quote)

    Example:
        >>> normalize_symbol("ETH-USDC")
        'ETH'
        >>> normalize_symbol("ETH")
        'ETH'
        >>> normalize_symbol("btc-usdc")
        'BTC'
    """
    if not symbol:
        raise ValueError("Symbol cannot be empty")

    # Strip whitespace, uppercase, split by "-"
    normalized = symbol.strip().upper()
    parts = normalized.split("-")

    # Take first part (base asset)
    base = parts[0]

    return base


def map_order_books_to_trading_pairs(order_books: List) -> List[TradingPair]:
    """
    Map OrderBook list → TradingPair list

    Args:
        order_books: List of OrderBook objects from OrderApi.order_books()

    Returns:
        List of TradingPair domain models

    Note:
        max_leverage is set to None (not available in OrderBook).
        Use min_leverage=1.0 as default.
    """
    pairs = []

    for order_book in order_books:
        try:
            # Extract fields from OrderBook
            market_id = getattr(order_book, 'market_id', None)
            if market_id is None:
                logger.warning(f"OrderBook missing market_id, skipping: {order_book}")
                continue

            symbol_raw = getattr(order_book, 'symbol', None)
            if not symbol_raw:
                logger.warning(f"OrderBook missing symbol for market_id={market_id}, skipping")
                continue

            # Normalize symbol and construct canonical format
            symbol_base = normalize_symbol(symbol_raw)
            symbol_canonical = f"{symbol_base}-USDC"  # Canonical format

            # Parse base/quote from symbol
            base = symbol_base
            quote = "USDC"  # Assumed for perpetuals

            # Fees (0.0000 = 0%)
            maker_fee = float(getattr(order_book, 'maker_fee', 0.0))
            taker_fee = float(getattr(order_book, 'taker_fee', 0.0))

            # Market status
            status = getattr(order_book, 'status', 'unknown')
            is_market_open = (status == 'active')

            # Create TradingPair
            pair = TradingPair(
                pair_id=market_id,
                symbol=symbol_canonical,
                base=base,
                quote=quote,
                min_leverage=1.0,  # Default (not in OrderBook)
                max_leverage=None,  # Not available in OrderBook
                maker_fee_percent=maker_fee,
                taker_fee_percent=taker_fee,
                is_market_open=is_market_open,
            )

            pairs.append(pair)

        except Exception as e:
            logger.error(f"Error mapping OrderBook to TradingPair: {e}, order_book={order_book}")
            continue

    logger.debug(f"Mapped {len(pairs)}/{len(order_books)} trading pairs")
    return pairs


def map_order_book_orders_to_price_data(
    symbol: str,
    order_book_orders,
    time_provider: Callable[[], datetime] = datetime.now,
) -> PriceData:
    """
    Map OrderBookOrders → PriceData

    Args:
        symbol: Trading symbol (e.g., "ETH" or "ETH-USDC")
        order_book_orders: OrderBookOrders object from OrderApi.order_book_orders()
        time_provider: Function returning current datetime (for tests)

    Returns:
        PriceData domain model

    Raises:
        NoLiquidityError: If no bids or asks available
    """
    # Normalize symbol
    symbol_normalized = normalize_symbol(symbol)

    # Extract bids and asks
    bids = getattr(order_book_orders, 'bids', []) or []
    asks = getattr(order_book_orders, 'asks', []) or []

    # Get best bid/ask
    best_bid = None
    best_ask = None

    if bids:
        first_bid = bids[0]
        bid_price_str = getattr(first_bid, 'price', None)
        if bid_price_str:
            try:
                best_bid = float(bid_price_str)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid bid price '{bid_price_str}': {e}")

    if asks:
        first_ask = asks[0]
        ask_price_str = getattr(first_ask, 'price', None)
        if ask_price_str:
            try:
                best_ask = float(ask_price_str)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid ask price '{ask_price_str}': {e}")

    # Validate liquidity
    if best_bid is None and best_ask is None:
        raise NoLiquidityError(
            symbol=symbol_normalized,
            reason="No bids or asks in orderbook",
            details={"bids_count": len(bids), "asks_count": len(asks)},
        )

    # Calculate mid price
    if best_bid is not None and best_ask is not None:
        bid = best_bid
        ask = best_ask
        mid = (bid + ask) / 2.0
    elif best_bid is not None:
        # Only bid available
        bid = best_bid
        ask = best_bid  # Use bid as reference
        mid = best_bid
    else:
        # Only ask available
        bid = best_ask  # Use ask as reference
        ask = best_ask
        mid = best_ask

    # Get timestamp
    timestamp = time_provider()

    return PriceData(
        symbol=symbol_normalized,
        bid=bid,
        ask=ask,
        mid=mid,
        timestamp=timestamp,
    )


def map_account_to_positions(account_response) -> List[Position]:
    """
    Map AccountApi.account() response → List[Position] (open positions only).

    Uses by='l1_address' response shape: accounts[].positions[].
    Filters out positions with size "0.00000".
    position_id format: "{pair_id}:{trade_index}" with pair_id=market_id, trade_index=index.

    References:
    - lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Positions API, by=l1_address
    """
    positions_out: List[Position] = []
    accounts = getattr(account_response, "accounts", []) or []
    if not accounts:
        return positions_out

    account = accounts[0]
    raw_positions = getattr(account, "positions", []) or []
    now = datetime.now(timezone.utc)

    for idx, pos in enumerate(raw_positions):
        size_str = getattr(pos, "position", "0") or "0"
        try:
            size_float = float(size_str)
        except (ValueError, TypeError):
            continue
        if size_float == 0.0:
            continue

        market_id = getattr(pos, "market_id", None)
        if market_id is None:
            continue
        symbol_raw = getattr(pos, "symbol", "") or ""
        symbol = normalize_symbol(symbol_raw) if symbol_raw else f"MKT{market_id}"
        sign = getattr(pos, "sign", 1)
        is_long = sign == 1

        entry_str = getattr(pos, "avg_entry_price", "0") or "0"
        try:
            open_price = float(entry_str)
        except (ValueError, TypeError):
            open_price = 0.0
        if open_price <= 0:
            continue

        value_str = getattr(pos, "position_value", "0") or "0"
        try:
            notional = float(value_str)
        except (ValueError, TypeError):
            notional = size_float * open_price

        # unrealized_pnl i mark_price oficials de Lighter (coincideixen amb la web)
        unrealized_pnl: Optional[float] = None
        mark_price: Optional[float] = None
        upnl_str = getattr(pos, "unrealized_pnl", None)
        if upnl_str is not None:
            try:
                unrealized_pnl = float(upnl_str)
                # Derive mark_price: unrealized_pnl = (mark - entry) * size (long) o (entry - mark) * size (short)
                if size_float > 0:
                    if is_long:
                        mark_price = open_price + (unrealized_pnl / size_float)
                    else:
                        mark_price = open_price - (unrealized_pnl / size_float)
            except (ValueError, TypeError):
                pass

        # pair_id + trade_index → position_id = "{pair_id}:{trade_index}"
        positions_out.append(
            Position(
                pair_id=market_id,
                trade_index=idx,
                symbol=symbol,
                is_long=is_long,
                collateral=notional,
                leverage=1.0,
                open_price=open_price,
                current_price=open_price,
                notional=notional,
                open_time=now,
                mark_price=mark_price,
                unrealized_pnl=unrealized_pnl,
            )
        )

    logger.debug(f"map_account_to_positions: {len(positions_out)} open positions")
    return positions_out


def _get_acc_attr(account: Any, key: str, default: Any = None) -> Any:
    """Get attribute from account (SDK object or dict)."""
    if hasattr(account, key):
        return getattr(account, key)
    if isinstance(account, dict):
        return account.get(key, default)
    return default


def map_account_to_balance(account_response: Any) -> Balance:
    """
    Map AccountApi.account() response → Balance (M2).

    Uses accounts[0]: total_asset_value, available_balance, collateral, assets[].
    assets[] items: symbol, asset_id, balance, locked_balance.
    USDC: from assets if symbol USDC else total_asset_value (equity USD).
    native_token: from assets ETH balance.

    References:
    - lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Account structure per get_balance (M2)
    """
    accounts = getattr(account_response, "accounts", []) or []
    if isinstance(account_response, dict):
        accounts = account_response.get("accounts") or []
    if not accounts:
        return Balance(usdc=0.0, native_token=0.0, available_margin=0.0, used_margin=0.0)

    account = accounts[0]
    total_str = _get_acc_attr(account, "total_asset_value") or "0"
    avail_str = _get_acc_attr(account, "available_balance") or "0"
    coll_str = _get_acc_attr(account, "collateral") or "0"
    try:
        total = float(total_str)
    except (ValueError, TypeError):
        total = 0.0
    try:
        available_margin = float(avail_str)
    except (ValueError, TypeError):
        available_margin = 0.0
    try:
        collateral = float(coll_str)
    except (ValueError, TypeError):
        collateral = 0.0
    used_margin = max(0.0, collateral - available_margin) if collateral >= available_margin else 0.0

    usdc = total
    native_token = 0.0
    raw_assets = _get_acc_attr(account, "assets") or []
    for a in raw_assets:
        symbol = (getattr(a, "symbol", None) or (a.get("symbol") if isinstance(a, dict) else None)) or ""
        symbol = symbol.strip().upper()
        bal_str = getattr(a, "balance", None) if not isinstance(a, dict) else a.get("balance", "0")
        try:
            bal = float(bal_str or "0")
        except (ValueError, TypeError):
            bal = 0.0
        if symbol == "USDC":
            usdc = bal
            break
    else:
        usdc = total
    for a in raw_assets:
        symbol = (getattr(a, "symbol", None) or (a.get("symbol") if isinstance(a, dict) else None)) or ""
        symbol = symbol.strip().upper()
        bal_str = getattr(a, "balance", None) if not isinstance(a, dict) else a.get("balance", "0")
        try:
            bal = float(bal_str or "0")
        except (ValueError, TypeError):
            bal = 0.0
        if symbol == "ETH":
            native_token = bal
            break

    return Balance(
        usdc=usdc,
        native_token=native_token,
        available_margin=available_margin,
        used_margin=used_margin,
    )
