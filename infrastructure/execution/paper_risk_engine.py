"""
PaperRiskEngine — P3.0 TP/SL/Liquidation triggers per paper trading

S'executa en cada update de preu (tick). Comprova:
- TP/SL triggers (mark_price vs sl_price/tp_price)
- Liquidation (equity <= notional * maintenance_margin_ratio)

Determinista, zero tx. Documentat a SAFETY_RUNBOOK.
"""

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from foundation.config.constants import (
    DEFAULT_PAPER_MAINTENANCE_MARGIN_RATIO,
    PAPER_MAINTENANCE_MARGIN_RATIO_ENV,
)
from foundation.logging import get_logger

logger = get_logger(__name__)


def _get_maintenance_margin_ratio() -> float:
    """Llegeix PAPER_MAINTENANCE_MARGIN_RATIO des de env (0.05 default)."""
    import os
    val = os.getenv(PAPER_MAINTENANCE_MARGIN_RATIO_ENV, "")
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return DEFAULT_PAPER_MAINTENANCE_MARGIN_RATIO


class PaperRiskEngine:
    """
    Risk engine per paper: TP/SL + liquidation.
    S'executa en cada tick; crida check_stops_and_liquidation del PaperExecutionEngine.
    """

    def __init__(
        self,
        engine,  # PaperExecutionEngine
        get_price: Callable[[str], Awaitable[float]],
        symbols: List[str],
        poll_interval_s: float = 1.0,
    ):
        self._engine = engine
        self._get_price = get_price
        self._symbols = symbols
        self._poll_interval_s = poll_interval_s
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._maintenance_ratio = _get_maintenance_margin_ratio()

    async def start(self) -> None:
        """Arrenca el loop de risk checks."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "PaperRiskEngine started: symbols=%s poll_interval_s=%s maintenance_ratio=%s",
            self._symbols,
            self._poll_interval_s,
            self._maintenance_ratio,
        )

    async def stop(self) -> None:
        """Atura el loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("PaperRiskEngine stopped")

    async def _run_loop(self) -> None:
        """Loop: cada poll_interval_s, obté preus i executa check_stops_and_liquidation."""
        while self._running:
            try:
                await asyncio.sleep(self._poll_interval_s)
                if not self._running:
                    break
                prices: Dict[str, float] = {}
                for sym in self._symbols:
                    try:
                        px = await self._get_price(sym)
                        if px is not None and px > 0:
                            prices[sym] = px
                    except Exception as e:
                        logger.debug("PaperRiskEngine get_price %s: %s", sym, e)
                if prices:
                    await self._engine.check_stops_and_liquidation(
                        current_prices=prices,
                        maintenance_margin_ratio=self._maintenance_ratio,
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("PaperRiskEngine loop error: %s", e)
