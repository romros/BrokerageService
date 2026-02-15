"""
PaperVenueAdapter — IVenueAdapter amb execució simulada (zero tx)

PAPER canònic: mainnet market data + paper execution.
Backed by PaperExecutionEngine. Preu des del price provider (mainnet).
"""

from datetime import datetime, timezone
from typing import Callable, Awaitable, List, Optional

from domain.interfaces import IVenueAdapter
from domain.models import (
    PriceData,
    Position,
    Balance,
    TradingPair,
    TradeFill,
    OrderResult,
    OrderRequest,
    OrderSide,
    OrderType,
    PositionMetrics,
)
from domain.models.trade import CLOSE_REASON_MANUAL
from foundation.config.constants import DEFAULT_INITIAL_BALANCE_USDC
from foundation.logging import get_logger

# Lazy: evita circular
from infrastructure.execution.paper_engine import PaperExecutionEngine
from infrastructure.execution.paper_risk_engine import PaperRiskEngine

logger = get_logger(__name__)

PAPER_VENUE_ID = "paper"


class PaperVenueAdapter(IVenueAdapter):
    """
    Adapter paper: execució simulada, zero tx.
    Preu des del price provider (mainnet feed).
    """

    def __init__(
        self,
        get_price: Callable[[str], Awaitable[PriceData]],
        symbols: List[str],
        initial_balance: float = DEFAULT_INITIAL_BALANCE_USDC,
        slippage_bps: float = 5.0,
    ):
        self._get_price = get_price
        self._symbols = symbols
        self._engine = PaperExecutionEngine(
            initial_balance=initial_balance,
            slippage_bps=slippage_bps,
        )
        # P3.0: Risk engine per TP/SL/liquidation
        async def _get_price_mid(sym: str) -> float:
            px = await self._get_price(sym)
            return float(px.mid or 0) if px else 0.0

        self._risk_engine = PaperRiskEngine(
            engine=self._engine,
            get_price=_get_price_mid,
            symbols=list(symbols),
        )

    async def start(self) -> None:
        await self._risk_engine.start()
        logger.info("PaperVenueAdapter started (execution_mode=paper_simulated, risk_engine=on)")

    async def stop(self) -> None:
        await self._risk_engine.stop()

    async def health_check(self) -> bool:
        return True

    async def get_latest_price(self, symbol: str) -> PriceData:
        return await self._get_price(symbol)

    async def stream_prices(self, symbol: str):
        raise NotImplementedError("PaperVenueAdapter: use get_latest_price")

    async def get_pairs(self) -> List[TradingPair]:
        return [
            TradingPair(
                pair_id=i,
                symbol=s,
                base=s,
                quote="USDC",
                min_leverage=1.0,
                max_leverage=50.0,
                maker_fee_percent=0.0,
                taker_fee_percent=0.0,
            )
            for i, s in enumerate(self._symbols)
        ]

    async def open_position(
        self,
        symbol: str,
        is_long: bool,
        collateral: float,
        leverage: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResult:
        px = await self._get_price(symbol)
        mid = px.mid or 0
        if mid <= 0:
            return OrderResult(
                success=False,
                position_id="",
                error_message=f"No price for {symbol}",
                timestamp=datetime.now(timezone.utc),
            )
        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.BUY if is_long else OrderSide.SELL,
            collateral=collateral,
            leverage=leverage,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        coid = client_order_id or f"paper_{symbol}_{datetime.now(timezone.utc).timestamp()}"
        result = await self._engine.open_position(request, coid, current_price=mid)
        if result.success:
            return OrderResult(
                success=True,
                position_id=result.position_id,
                order_id=result.order_id,
                executed_price=result.executed_price,
                executed_size=result.executed_size,
                fee=result.fee,
                slippage=result.slippage,
                timestamp=result.timestamp,
            )
        return result

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        internal_id = position_id
        if internal_id.startswith(f"{PAPER_VENUE_ID}:"):
            internal_id = internal_id[len(PAPER_VENUE_ID) + 1 :]
        pos = await self._engine.get_position(internal_id)
        if not pos:
            return False
        if percent < 100:
            # Paper engine no suporta close parcial; tancar 100%
            pass
        px = await self._get_price(pos.symbol)
        mid = px.mid or pos.open_price
        result = await self._engine.close_position(
            internal_id, f"close_{internal_id}", current_price=mid, close_reason=CLOSE_REASON_MANUAL
        )
        return result.success

    async def update_sl(self, position_id: str, new_sl: float) -> bool:
        internal_id = position_id
        if internal_id.startswith(f"{PAPER_VENUE_ID}:"):
            internal_id = internal_id[len(PAPER_VENUE_ID) + 1 :]
        try:
            await self._engine.update_sl(internal_id, new_sl)
            return True
        except ValueError:
            return False

    async def update_tp(self, position_id: str, new_tp: float) -> bool:
        internal_id = position_id
        if internal_id.startswith(f"{PAPER_VENUE_ID}:"):
            internal_id = internal_id[len(PAPER_VENUE_ID) + 1 :]
        try:
            await self._engine.update_tp(internal_id, new_tp)
            return True
        except ValueError:
            return False

    async def get_open_positions(self) -> List[Position]:
        return await self._engine.get_all_positions()

    async def get_position_metrics(self, position_id: str) -> PositionMetrics:
        raise NotImplementedError("PaperVenueAdapter: get_position_metrics")

    async def get_balance(self) -> Balance:
        return await self._engine.get_balance()

    async def get_trade_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[TradeFill]:
        return self._engine.get_trade_history(symbol=symbol, since=since, to=to, limit=limit)

    def get_mode(self) -> str:
        return "paper"

    @property
    def venue_name(self) -> str:
        return PAPER_VENUE_ID

    @property
    def is_live(self) -> bool:
        return False

    @property
    def is_paper(self) -> bool:
        return True

    @property
    def is_backtest(self) -> bool:
        return False
