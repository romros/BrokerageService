"""
ReconcileService — detect divergences between venue (source of truth) and local tracking.

Runs a loop every RECONCILE_INTERVAL_S; at each tick compares:
  venue_positions = adapter.get_open_positions()
  local_positions = local_provider.get_positions()

Emits ReconcileResult (missing_locally, extra_locally, mismatch) and logs when diffs exist.
DI-friendly: uses IVenueAdapter; time/sleep injectable for deterministic tests.
"""

import asyncio
import os
from typing import Awaitable, Callable, List, Optional

# Optional bootstrap run before loop (restart safety)
BootstrapFn = Callable[[], Awaitable[None]]
# Optional callback when a reconcile tick raises (for smoke runner error count)
OnTickErrorFn = Callable[[Exception], None]

from domain.interfaces import IVenueAdapter, IReconcileSink
from domain.models import (
    Position,
    ReconcileResult,
    PositionMismatch,
    ReconcileAction,
    MarkStalePosition,
    RequestResync,
)
from foundation.lifecycle import IService
from foundation.logging import get_logger

logger = get_logger(__name__)

DEFAULT_RECONCILE_INTERVAL_S = 60.0


def _position_key(p: Position) -> str:
    return p.position_id


def _mismatch_fields(venue: Position, local: Position) -> List[str]:
    """Return list of field names that differ (symbol, size, is_long)."""
    diff: List[str] = []
    if venue.symbol != local.symbol:
        diff.append("symbol")
    if venue.is_long != local.is_long:
        diff.append("is_long")
    # size: compare notional (position size in USD)
    v_size = venue.notional or (venue.collateral * venue.leverage)
    l_size = local.notional or (local.collateral * local.leverage)
    if v_size != l_size:
        diff.append("size")
    return diff


def compute_reconcile_result(
    venue_positions: List[Position],
    local_positions: List[Position],
) -> ReconcileResult:
    """
    Compare venue vs local positions; deterministic, no I/O.
    """
    venue_by_id = {_position_key(p): p for p in venue_positions}
    local_by_id = {_position_key(p): p for p in local_positions}

    missing_locally: List[Position] = []
    extra_locally: List[Position] = []
    mismatch: List[PositionMismatch] = []

    for pid, vp in venue_by_id.items():
        if pid not in local_by_id:
            missing_locally.append(vp)
            continue
        lp = local_by_id[pid]
        fields = _mismatch_fields(vp, lp)
        if fields:
            mismatch.append(
                PositionMismatch(
                    position_id=pid,
                    venue_position=vp,
                    local_position=lp,
                    fields_diff=fields,
                )
            )

    for pid, lp in local_by_id.items():
        if pid not in venue_by_id:
            extra_locally.append(lp)

    return ReconcileResult(
        missing_locally=missing_locally,
        extra_locally=extra_locally,
        mismatch=mismatch,
    )


def build_actions(
    result: ReconcileResult,
    venue_name: Optional[str] = None,
) -> List[ReconcileAction]:
    """
    Build reconcile actions from a ReconcileResult (pure, no I/O).
    - missing_locally -> RequestResync("missing_locally")
    - extra_locally -> MarkStalePosition per position
    - mismatch -> MarkStalePosition per position + RequestResync("mismatch")
    """
    actions: List[ReconcileAction] = []
    if result.missing_locally:
        actions.append(RequestResync("missing_locally", venue_name))
    for p in result.extra_locally:
        actions.append(MarkStalePosition(p.position_id, "extra_locally", []))
    for m in result.mismatch:
        reason = "mismatch:" + ",".join(m.fields_diff)
        actions.append(MarkStalePosition(m.position_id, reason, m.fields_diff))
    if result.mismatch:
        actions.append(RequestResync("mismatch", venue_name))
    return actions


# Provider: callable that returns list of positions (async)
LocalPositionsProvider = Callable[[], Awaitable[List[Position]]]


class ReconcileService(IService):
    """
    Reconcile loop: compare venue vs local positions every interval_sec.
    Uses injectable sleep_fn for deterministic tests (no real sleep).
    """

    def __init__(
        self,
        adapter: IVenueAdapter,
        local_provider: LocalPositionsProvider,
        interval_sec: float,
        *,
        sleep_fn: Optional[Callable[[float], Awaitable[None]]] = None,
        reconcile_sink: Optional[IReconcileSink] = None,
        venue_name: Optional[str] = None,
        bootstrap_fn: Optional[BootstrapFn] = None,
        on_tick_error: Optional[OnTickErrorFn] = None,
    ):
        self.adapter = adapter
        self.local_provider = local_provider
        self.interval_sec = interval_sec
        self._sleep_fn = sleep_fn or asyncio.sleep
        self._reconcile_sink = reconcile_sink
        self._venue_name = venue_name
        self._bootstrap_fn = bootstrap_fn
        self._on_tick_error = on_tick_error
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            logger.warning("ReconcileService already running")
            return
        logger.info(
            "ReconcileService starting interval_sec={}",
            self.interval_sec,
        )
        if self._bootstrap_fn is not None:
            await self._bootstrap_fn()
        self._running = True
        self._task = asyncio.create_task(self._reconcile_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("ReconcileService stopped")

    async def health_check(self) -> bool:
        return self._running

    @property
    def is_running(self) -> bool:
        return self._running

    async def _reconcile_loop(self) -> None:
        tick_num = 0
        while self._running:
            try:
                result = await self._run_one_tick()
                tick_num += 1
                logger.info("Reconcile tick #{} ok", tick_num)
                if result.has_diffs:
                    self._log_diffs(result)
                    if self._reconcile_sink is not None:
                        actions = build_actions(result, self._venue_name)
                        self._reconcile_sink.handle(actions)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Reconcile tick failed: {}", e)
                if self._on_tick_error is not None:
                    self._on_tick_error(e)
            await self._sleep_fn(self.interval_sec)

    async def _run_one_tick(self) -> ReconcileResult:
        venue_positions = await self.adapter.get_open_positions()
        local_positions = await self.local_provider()
        return compute_reconcile_result(venue_positions, local_positions)

    def _log_diffs(self, result: ReconcileResult) -> None:
        if result.missing_locally:
            logger.warning(
                "Reconcile: missing_locally (%s) %s",
                len(result.missing_locally),
                [p.position_id for p in result.missing_locally],
            )
        if result.extra_locally:
            logger.warning(
                "Reconcile: extra_locally (%s) %s",
                len(result.extra_locally),
                [p.position_id for p in result.extra_locally],
            )
        if result.mismatch:
            for m in result.mismatch:
                logger.warning(
                    "Reconcile: mismatch %s fields=%s",
                    m.position_id,
                    m.fields_diff,
                )


def reconcile_interval_sec_from_env() -> float:
    """Read RECONCILE_INTERVAL_S from env; default DEFAULT_RECONCILE_INTERVAL_S."""
    raw = os.getenv("RECONCILE_INTERVAL_S")
    if raw is None:
        return DEFAULT_RECONCILE_INTERVAL_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_RECONCILE_INTERVAL_S
