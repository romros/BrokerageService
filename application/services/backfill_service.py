"""
BackfillService - Periodic backfill to ensure "no gaps"

Responsibilities:
- Startup backfill: fills gaps from last_ts - corrective_window to now
- Periodic backfill: every N seconds (configurable)
- Detects gaps using GapValidator
- Fetches missing data via IBackfillProvider
- Patches store using store.patch()

Usage:
    service = BackfillService(
        store=csv_store,
        provider=mock_provider,
        symbols=["XAUUSD", "EURUSD"],
        corrective_window_minutes=5,
        interval_seconds=600,
    )

    await service.start()  # Runs startup backfill
    # ... service runs periodic backfill in background
    await service.stop()
"""


from datetime import datetime, timedelta
from typing import List, Optional
import asyncio

from zoneinfo import ZoneInfo

from domain.interfaces import ICandleStore, IBackfillProvider
from foundation.logging import get_logger
from infrastructure.storage.gap_validator import GapValidator


logger = get_logger(__name__)


class BackfillService:
    """
    Backfill service for ensuring data completeness

    Features:
    - Startup backfill (corrective window)
    - Periodic backfill (every N seconds)
    - Gap detection and filling
    - Per-symbol backfill
    """

    def __init__(
        self,
        store: ICandleStore,
        provider: IBackfillProvider,
        symbols: List[str],
        corrective_window_minutes: int = 5,
        interval_seconds: int = 600,
        tz: Optional[ZoneInfo] = None,
    ):
        """
        Initialize backfill service

        Args:
            store: Candle storage
            provider: Backfill data provider
            symbols: List of symbols to backfill
            corrective_window_minutes: Minutes to look back for corrections
            interval_seconds: Interval between periodic backfills
            tz: Timezone (default: America/New_York)
        """
        self.store = store
        self.provider = provider
        self.symbols = symbols
        self.corrective_window_minutes = corrective_window_minutes
        self.interval_seconds = interval_seconds
        self.tz = tz or ZoneInfo("America/New_York")

        self._running = False
        self._task: Optional[asyncio.Task] = None

        logger.info(
            f"BackfillService initialized: symbols={symbols}, "
            f"corrective_window={corrective_window_minutes}min, "
            f"interval={interval_seconds}s"
        )

    async def start(self) -> None:
        """
        Start backfill service

        - Runs startup backfill immediately
        - Starts periodic backfill loop
        """
        if self._running:
            logger.warning("BackfillService already running")
            return

        self._running = True

        # Check if provider is available
        is_available = await self.provider.is_available()
        if not is_available:
            logger.warning(
                f"Backfill provider '{self.provider.provider_name}' not available - "
                "backfill disabled"
            )
            return

        # Startup backfill
        logger.info("Running startup backfill...")
        await self._run_backfill_for_all_symbols()

        # Start periodic backfill loop
        self._task = asyncio.create_task(self._periodic_backfill_loop())

        logger.info("✓ BackfillService started")

    async def stop(self) -> None:
        """Stop backfill service"""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("BackfillService stopped")

    async def backfill_symbol(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> int:
        """
        Backfill a specific symbol

        Args:
            symbol: Trading pair
            start: Start timestamp (default: last_ts - corrective_window)
            end: End timestamp (default: now)

        Returns:
            Number of candles filled
        """
        # Determine time range
        if end is None:
            end = datetime.now(self.tz)

        if start is None:
            # Get last timestamp from store
            last_ts = self.store.get_last_timestamp(symbol)

            if last_ts is None:
                logger.warning(f"No data for {symbol} - skipping backfill")
                return 0

            # Start from last_ts - corrective_window
            start = last_ts - timedelta(minutes=self.corrective_window_minutes)

        # Align to minute boundaries
        start = start.replace(second=0, microsecond=0)
        end = end.replace(second=0, microsecond=0)

        logger.info(f"Backfilling {symbol}: [{start} to {end}]")

        # Read current data
        current_range = self.store.read_range(symbol, start, end, validate_gaps=True)

        if current_range.is_complete:
            logger.debug(f"✓ {symbol} already complete (no gaps)")
            return 0

        # Find gaps
        gaps = GapValidator.find_gaps(current_range.candles, start, end)

        logger.info(
            f"Found {len(gaps)} gaps in {symbol} "
            f"({current_range.missing_count} missing candles)"
        )

        # Fetch missing data
        total_filled = 0

        for gap in gaps:
            logger.debug(f"Filling gap: {gap}")

            try:
                # Fetch from provider
                candles = await self.provider.fetch_ohlcv(symbol, gap.start, gap.end)

                if not candles:
                    logger.warning(f"Provider returned no data for gap {gap}")
                    continue

                # Patch store
                written = self.store.patch(candles)
                total_filled += written

                logger.debug(f"✓ Filled {written} candles for gap {gap}")

            except Exception as e:
                logger.error(f"Failed to fill gap {gap}: {e}")
                continue

        logger.info(f"✓ Backfilled {total_filled} candles for {symbol}")
        return total_filled

    async def _run_backfill_for_all_symbols(self) -> None:
        """Run backfill for all configured symbols"""
        total_filled = 0

        for symbol in self.symbols:
            try:
                filled = await self.backfill_symbol(symbol)
                total_filled += filled
            except Exception as e:
                logger.error(f"Backfill failed for {symbol}: {e}")
                continue

        logger.info(f"✓ Backfill complete: {total_filled} total candles filled")

    async def _periodic_backfill_loop(self) -> None:
        """Periodic backfill loop (runs every interval_seconds)"""
        logger.info(f"Periodic backfill started (every {self.interval_seconds}s)")

        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)

                if not self._running:
                    break

                logger.debug("Running periodic backfill...")
                await self._run_backfill_for_all_symbols()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic backfill error: {e}")
                # Continue loop even on error
                await asyncio.sleep(10)

        logger.info("Periodic backfill loop stopped")
