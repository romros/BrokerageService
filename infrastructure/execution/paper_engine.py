"""
PaperExecutionEngine - Simulated order execution for paper trading

Features:
- Realistic fills with configurable slippage
- Official gTrade fee calculation using CostModel
- In-memory position management
- Stop loss / take profit monitoring
- Balance tracking
- WebSocket event emission for real-time updates

Usage:
    from infrastructure.ws import get_hub

    engine = PaperExecutionEngine(
        initial_balance=10000.0,
        slippage_bps=5.0,  # 5 basis points
        hub=get_hub(),  # Optional: for WS broadcasting
    )

    result = await engine.open_position(request, "client_order_123", current_price=2700.0)
"""


from datetime import datetime
from typing import Optional, Dict, TYPE_CHECKING
import uuid

from zoneinfo import ZoneInfo

from foundation.config.constants import (


    BASIS_POINTS_DIVISOR,
    CANONICAL_TIMEZONE,
    DEFAULT_INITIAL_BALANCE_USDC,
)
from domain.interfaces import IExecutionEngine
from domain.models import Position, OrderRequest, OrderResult, OrderSide, Balance, TradeFill
from domain.models.cost_model import CostModel
from domain.models.enums import PositionAction
from domain.models.trade import (
    CLOSE_REASON_LIQUIDATION,
    CLOSE_REASON_MANUAL,
    CLOSE_REASON_STOP_LOSS,
    CLOSE_REASON_TAKE_PROFIT,
    CLOSE_REASON_TTL,
)
from foundation.logging import get_logger

if TYPE_CHECKING:
    from infrastructure.ws.hub import WebSocketHub

logger = get_logger(__name__)


class PaperExecutionEngine(IExecutionEngine):
    """
    Paper trading execution engine

    Simulates order execution with realistic slippage and fees.
    """

    def __init__(
        self,
        initial_balance: float = DEFAULT_INITIAL_BALANCE_USDC,
        slippage_bps: float = 5.0,  # 5 basis points (0.05%)
        tz: Optional[ZoneInfo] = None,
        hub: Optional["WebSocketHub"] = None,
    ):
        """
        Initialize paper execution engine

        Uses official gTrade CostModel for fees per symbol.

        Args:
            initial_balance: Starting USDC balance
            slippage_bps: Slippage in basis points (100 bps = 1%)
            tz: Timezone (default: America/New_York)
            hub: WebSocketHub for real-time broadcasting (optional)
        """
        self._balance = initial_balance
        self._initial_balance = initial_balance
        self._positions: Dict[str, Position] = {}  # position_id -> Position
        self._trade_history: list[TradeFill] = []  # P3.0: closed trades amb close_reason
        self._slippage_bps = slippage_bps
        self._tz = tz or CANONICAL_TIMEZONE
        self._hub = hub

        logger.info(
            f"PaperExecutionEngine initialized: balance=${initial_balance:.2f}, "
            f"slippage={slippage_bps}bps, using official gTrade CostModel, "
            f"WS broadcasting={'enabled' if hub else 'disabled'}"
        )

    async def open_position(
        self,
        request: OrderRequest,
        client_order_id: str,
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> OrderResult:
        """
        Open a new position (simulated)

        Args:
            request: Order parameters
            client_order_id: Idempotency key
            current_price: Current market price
            timestamp: Execution timestamp

        Returns:
            OrderResult with position details
        """
        if timestamp is None:
            timestamp = datetime.now(self._tz)

        # Calculate position size
        notional = request.collateral * request.leverage

        # Check if sufficient balance
        if request.collateral > self._balance:
            return OrderResult(
                success=False,
                position_id="",
                error_message=f"Insufficient balance: ${self._balance:.2f} < ${request.collateral:.2f}",
                timestamp=timestamp,
            )

        # Get cost model for symbol
        try:
            cost_model = CostModel.for_gtrade_symbol(request.symbol)
        except ValueError as e:
            return OrderResult(
                success=False,
                position_id="",
                error_message=str(e),
                timestamp=timestamp,
            )

        # Apply slippage (adverse for trader)
        slippage_factor = self._slippage_bps / BASIS_POINTS_DIVISOR
        if request.side == OrderSide.BUY:
            executed_price = current_price * (1 + slippage_factor)
        else:
            executed_price = current_price * (1 - slippage_factor)

        # Calculate fees using CostModel
        open_fees = cost_model.calculate_open_fees(notional)
        total_entry_fee = open_fees["total_entry_cost"]

        # Deduct collateral + fee from balance
        total_cost = request.collateral + total_entry_fee
        self._balance -= total_cost

        # Create position
        position_id = f"paper_{uuid.uuid4().hex[:12]}"
        position = Position(
            pair_id=0,  # Paper mode doesn't use pair_id
            trade_index=0,
            symbol=request.symbol,
            is_long=(request.side == OrderSide.BUY),
            collateral=request.collateral,
            leverage=request.leverage,
            open_price=executed_price,
            current_price=executed_price,
            sl_price=request.sl_price,
            tp_price=request.tp_price,
            open_time=timestamp,
            notional=notional,
            venue_position_id=position_id,
        )

        self._positions[position_id] = position

        logger.info(
            f"✓ Opened position {position_id}: {request.symbol} {request.side.value.upper()} "
            f"${notional:.2f} @ ${executed_price:.2f} (collateral=${request.collateral:.2f}, "
            f"leverage={request.leverage}x, fee=${total_entry_fee:.2f})"
        )

        # Broadcast to WebSocket subscribers (async, non-blocking)
        await self._broadcast_position_event(position_id, PositionAction.OPENED)
        await self._broadcast_execution_event(position_id, request.symbol, PositionAction.OPENED, executed_price, total_entry_fee)
        await self._broadcast_balance_event()

        size_base = notional / executed_price if executed_price else 0
        return OrderResult(
            success=True,
            position_id=position_id,
            order_id=client_order_id,
            executed_price=executed_price,
            executed_size=size_base,  # Base units (ex. ETH amount) per broker contract
            fee=total_entry_fee,
            slippage=self._slippage_bps,
            timestamp=timestamp,
            fees_breakdown=open_fees,
        )

    async def close_position(
        self,
        position_id: str,
        client_order_id: str,
        current_price: float,
        timestamp: Optional[datetime] = None,
        close_reason: str = CLOSE_REASON_MANUAL,
    ) -> OrderResult:
        """
        Close an existing position

        Args:
            position_id: Position to close
            client_order_id: Idempotency key
            current_price: Current market price
            timestamp: Execution timestamp

        Returns:
            OrderResult with PnL details
        """
        if timestamp is None:
            timestamp = datetime.now(self._tz)

        # Check if position exists
        if position_id not in self._positions:
            return OrderResult(
                success=False,
                position_id=position_id,
                error_message=f"Position {position_id} not found",
                timestamp=timestamp,
            )

        position = self._positions[position_id]

        # Get cost model for symbol
        try:
            cost_model = CostModel.for_gtrade_symbol(position.symbol)
        except ValueError as e:
            return OrderResult(
                success=False,
                position_id=position_id,
                error_message=str(e),
                timestamp=timestamp,
            )

        # Apply slippage (adverse for trader)
        slippage_factor = self._slippage_bps / BASIS_POINTS_DIVISOR
        if position.is_long:
            # Closing long = sell, get lower price
            executed_price = current_price * (1 - slippage_factor)
        else:
            # Closing short = buy, pay higher price
            executed_price = current_price * (1 + slippage_factor)

        # Calculate gross PnL (before fees)
        price_diff = executed_price - position.open_price
        if not position.is_long:
            price_diff = -price_diff  # Invert for short

        pnl_gross = price_diff * position.leverage * position.collateral / position.open_price

        # Calculate fees using CostModel
        close_fees = cost_model.calculate_close_fees(position.notional)
        total_exit_fee = close_fees["total_exit_cost"]

        # Net PnL after fees
        pnl_net = pnl_gross - total_exit_fee

        # Return collateral + PnL to balance
        self._balance += position.collateral + pnl_net

        # Calculate PnL percentages
        pnl_gross_percent = (pnl_gross / position.collateral) * 100
        pnl_net_percent = (pnl_net / position.collateral) * 100

        # P3.0: Store trade history amb close_reason
        size_base = position.notional / executed_price if executed_price else 0
        trade_fill = TradeFill(
            trade_id=f"paper_{position_id}_{int(timestamp.timestamp())}",
            symbol=position.symbol,
            side="sell" if position.is_long else "buy",
            price=executed_price,
            size=size_base,
            fee=total_exit_fee,
            timestamp=timestamp,
            order_id=client_order_id,
            position_id=position_id,
            close_reason=close_reason,
            open_ts=position.open_time,
            close_ts=timestamp,
            open_price=position.open_price,
            close_price=executed_price,
        )
        self._trade_history.append(trade_fill)

        # Remove position
        del self._positions[position_id]

        logger.info(
            f"✓ Closed position {position_id}: {position.symbol} {position.side} "
            f"PnL_net=${pnl_net:.2f} ({pnl_net_percent:+.2f}%) PnL_gross=${pnl_gross:.2f} "
            f"@ ${executed_price:.2f} (open=${position.open_price:.2f}, fee=${total_exit_fee:.2f})"
        )

        # Broadcast to WebSocket subscribers
        await self._broadcast_position_event(position_id, PositionAction.CLOSED)
        await self._broadcast_execution_event(position_id, position.symbol, PositionAction.CLOSED, executed_price, total_exit_fee, pnl_net)
        await self._broadcast_balance_event()

        return OrderResult(
            success=True,
            position_id=position_id,
            order_id=client_order_id,
            executed_price=executed_price,
            executed_size=position.notional,
            fee=total_exit_fee,
            slippage=self._slippage_bps,
            realized_pnl=pnl_net,
            realized_pnl_percent=pnl_net_percent,
            pnl_gross=pnl_gross,
            pnl_gross_percent=pnl_gross_percent,
            timestamp=timestamp,
            fees_breakdown=close_fees,
        )

    async def update_sl(self, position_id: str, new_sl: Optional[float]) -> None:
        """Update stop loss for a position"""
        if position_id not in self._positions:
            raise ValueError(f"Position {position_id} not found")

        self._positions[position_id].sl_price = new_sl
        logger.info(f"Updated SL for {position_id}: {new_sl}")

        # Broadcast position update
        await self._broadcast_position_event(position_id, PositionAction.UPDATED)

    async def update_tp(self, position_id: str, new_tp: Optional[float]) -> None:
        """Update take profit for a position"""
        if position_id not in self._positions:
            raise ValueError(f"Position {position_id} not found")

        self._positions[position_id].tp_price = new_tp
        logger.info(f"Updated TP for {position_id}: {new_tp}")

        # Broadcast position update
        await self._broadcast_position_event(position_id, PositionAction.UPDATED)

    async def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID"""
        return self._positions.get(position_id)

    async def get_all_positions(self) -> list[Position]:
        """Get all open positions"""
        return list(self._positions.values())

    async def get_balance(self) -> Balance:
        """Get current account balance"""
        # Calculate used margin (sum of all collateral)
        used_margin = sum(p.collateral for p in self._positions.values())

        return Balance(
            usdc=self._balance,
            native_token=0.0,  # Paper mode doesn't track gas
            available_margin=self._balance,
            used_margin=used_margin,
        )

    async def check_stops(self, current_prices: dict[str, float]) -> list[OrderResult]:
        """
        Check if any positions hit stop loss or take profit

        Args:
            current_prices: Dict of symbol -> current price

        Returns:
            List of OrderResults for positions that were closed
        """
        closed_positions = []

        for position_id, position in list(self._positions.items()):
            current_price = current_prices.get(position.symbol)

            if current_price is None:
                continue

            # Update current price
            position.current_price = current_price

            # Check stop loss
            if position.sl_price is not None:
                if position.is_long and current_price <= position.sl_price:
                    logger.info(f"Stop loss hit for {position_id}: {current_price} <= {position.sl_price}")
                    result = await self.close_position(
                        position_id, f"sl_{position_id}", current_price, close_reason=CLOSE_REASON_STOP_LOSS
                    )
                    closed_positions.append(result)
                    continue

                if not position.is_long and current_price >= position.sl_price:
                    logger.info(f"Stop loss hit for {position_id}: {current_price} >= {position.sl_price}")
                    result = await self.close_position(
                        position_id, f"sl_{position_id}", current_price, close_reason=CLOSE_REASON_STOP_LOSS
                    )
                    closed_positions.append(result)
                    continue

            # Check take profit
            if position.tp_price is not None:
                if position.is_long and current_price >= position.tp_price:
                    logger.info(f"Take profit hit for {position_id}: {current_price} >= {position.tp_price}")
                    result = await self.close_position(
                        position_id, f"tp_{position_id}", current_price, close_reason=CLOSE_REASON_TAKE_PROFIT
                    )
                    closed_positions.append(result)
                    continue

                if not position.is_long and current_price <= position.tp_price:
                    logger.info(f"Take profit hit for {position_id}: {current_price} <= {position.tp_price}")
                    result = await self.close_position(
                        position_id, f"tp_{position_id}", current_price, close_reason=CLOSE_REASON_TAKE_PROFIT
                    )
                    closed_positions.append(result)
                    continue

        return closed_positions

    async def check_stops_and_liquidation(
        self,
        current_prices: dict[str, float],
        maintenance_margin_ratio: float = 0.05,
    ) -> list[OrderResult]:
        """
        P3.0: Check TP/SL + liquidation. Liquidation si equity <= notional * maintenance_margin_ratio.
        equity = collateral + unrealized_pnl
        """
        closed = []

        # Liquidation check (abans de TP/SL per prioritat)
        for position_id, position in list(self._positions.items()):
            current_price = current_prices.get(position.symbol)
            if current_price is None:
                continue
            position.current_price = current_price

            # equity = collateral + unrealized_pnl
            size = (position.notional or 0) / (position.open_price or 1)
            if position.is_long:
                unrealized_pnl = (current_price - position.open_price) * size
            else:
                unrealized_pnl = (position.open_price - current_price) * size
            equity = position.collateral + unrealized_pnl
            notional = position.notional or (position.collateral * position.leverage)
            maintenance_margin = notional * maintenance_margin_ratio

            if equity <= maintenance_margin:
                logger.info(
                    f"Liquidation for {position_id}: equity={equity:.2f} <= maintenance={maintenance_margin:.2f}"
                )
                result = await self.close_position(
                    position_id, f"liq_{position_id}", current_price, close_reason=CLOSE_REASON_LIQUIDATION
                )
                closed.append(result)
                continue

        # TP/SL (només posicions no liquidades)
        closed.extend(await self.check_stops(current_prices))
        return closed

    async def check_ttl(self, ttl_s: float) -> list:
        """
        T7.1: Tanca posicions que superen ttl_s des de l'obertura.
        Usa current_price (última coneguda) o open_price com a fallback.
        Retorna llista d'OrderResult de posicions tancades.
        """
        closed = []
        now = datetime.now(self._tz)
        for position_id, position in list(self._positions.items()):
            if position.open_time is None:
                continue
            # Normalitza timezone per comparació
            open_time = position.open_time
            if open_time.tzinfo is None:
                open_time = open_time.replace(tzinfo=self._tz)
            age_s = (now - open_time).total_seconds()
            if age_s >= ttl_s:
                price = position.current_price or position.open_price
                logger.info(
                    "TTL close position=%s symbol=%s age_s=%.0f ttl_s=%.0f price=%.5f",
                    position_id,
                    position.symbol,
                    age_s,
                    ttl_s,
                    price,
                )
                result = await self.close_position(
                    position_id,
                    f"ttl_{position_id}",
                    current_price=price,
                    close_reason=CLOSE_REASON_TTL,
                )
                closed.append(result)
        return closed

    def get_trade_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[TradeFill]:
        """P3.0: Retorna trades tancats amb close_reason."""
        out = list(self._trade_history)
        if symbol:
            out = [t for t in out if t.symbol == symbol]
        if since:
            out = [t for t in out if t.timestamp and t.timestamp >= since]
        if to:
            out = [t for t in out if t.timestamp and t.timestamp <= to]
        out.sort(key=lambda t: (t.timestamp or datetime.min).timestamp(), reverse=True)
        return out[:limit]

    # ============ WebSocket Broadcasting ============

    async def _broadcast_position_event(self, position_id: str, action: str) -> None:
        """
        Broadcast position event to WebSocket subscribers

        Args:
            position_id: Position ID
            action: "opened", "closed", "updated"
        """
        if self._hub is None:
            return

        try:
            # Lazy: evita circular infrastructure.ws ↔ paper_engine
            from infrastructure.ws import create_position_message

            position = self._positions.get(position_id)

            # If position doesn't exist (closed), send minimal data
            if position is None:
                data = {
                    "position_id": position_id,
                    "action": action,
                }
            else:
                data = {
                    "position_id": position_id,
                    "action": action,
                    "symbol": position.symbol,
                    "side": "buy" if position.is_long else "sell",
                    "collateral": position.collateral,
                    "leverage": position.leverage,
                    "open_price": position.open_price,
                    "current_price": position.current_price,
                    "sl_price": position.sl_price,
                    "tp_price": position.tp_price,
                    "unrealized_pnl": position.unrealized_pnl,
                    "unrealized_pnl_percent": position.unrealized_pnl_percent,
                }

            message = create_position_message(data)
            await self._hub.broadcast("positions", message)

        except Exception as e:
            logger.warning(f"Failed to broadcast position event: {e}")

    async def _broadcast_execution_event(
        self,
        position_id: str,
        symbol: str,
        action: str,
        price: float,
        fee: float,
        pnl: Optional[float] = None,
    ) -> None:
        """
        Broadcast execution event to WebSocket subscribers

        Args:
            position_id: Position ID
            symbol: Trading symbol
            action: "opened", "closed"
            price: Executed price
            fee: Fee paid
            pnl: Realized PnL (for close events)
        """
        if self._hub is None:
            return

        try:
            # Lazy: evita circular infrastructure.ws ↔ paper_engine
            from infrastructure.ws import create_execution_message

            data = {
                "position_id": position_id,
                "symbol": symbol,
                "action": action,
                "price": price,
                "fee": fee,
            }

            if pnl is not None:
                data["pnl"] = pnl

            message = create_execution_message(data)
            await self._hub.broadcast("execution", message)

        except Exception as e:
            logger.warning(f"Failed to broadcast execution event: {e}")

    async def _broadcast_balance_event(self) -> None:
        """Broadcast balance change to WebSocket subscribers"""
        if self._hub is None:
            return

        try:
            # Lazy: evita circular infrastructure.ws ↔ paper_engine
            from infrastructure.ws import create_balance_message

            balance = await self.get_balance()

            data = {
                "usdc": balance.usdc,
                "available_margin": balance.available_margin,
                "used_margin": balance.used_margin,
            }

            message = create_balance_message(data)
            await self._hub.broadcast("balance", message)

        except Exception as e:
            logger.warning(f"Failed to broadcast balance event: {e}")
