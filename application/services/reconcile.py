"""
Reconciliació mínima post-open / post-close (best-effort).

No bloqueja el flux principal. Registra WARNING si hi ha discrepàncies.
Bounded time: si get_open_positions falla, simplement logeja i continua.

Ús:
    await reconcile_open(adapter, position_id, symbol, venue)
    await reconcile_close(adapter, position_id, venue)
"""

from typing import Any

from foundation.logging import get_logger

logger = get_logger(__name__)


async def reconcile_open(
    adapter: Any,
    position_id: str,
    symbol: str,
    venue: str,
) -> None:
    """
    Post-open: confirma que la posició apareix a get_open_positions.

    Best-effort: qualsevol excepció → log WARNING, no propaga.
    """
    try:
        positions = await adapter.get_open_positions()
        pid_norm = (position_id or "").strip()
        sym_upper = (symbol or "").strip().upper()
        found = False
        for p in positions:
            # Busca per position_id o per symbol (fallback)
            p_vid = str(getattr(p, "venue_position_id", "") or "")
            p_sym = (getattr(p, "symbol", "") or "").strip().upper()
            if pid_norm and p_vid and pid_norm in p_vid:
                found = True
                break
            if p_sym == sym_upper:
                found = True
                break
        if found:
            logger.info(
                "reconcile_open OK: position_id=%s symbol=%s venue=%s",
                position_id, symbol, venue,
            )
        else:
            logger.warning(
                "reconcile_open WARN: position %s (%s) not found in get_open_positions after open at %s",
                position_id, symbol, venue,
            )
    except Exception as e:
        logger.warning(
            "reconcile_open ERROR (best-effort, non-blocking): %s", e
        )


async def reconcile_close(
    adapter: Any,
    position_id: str,
    venue: str,
) -> None:
    """
    Post-close: confirma que la posició NO apareix a get_open_positions.

    Best-effort: qualsevol excepció → log WARNING, no propaga.
    """
    try:
        positions = await adapter.get_open_positions()
        pid_norm = (position_id or "").strip()
        still_open = False
        for p in positions:
            p_vid = str(getattr(p, "venue_position_id", "") or "")
            if pid_norm and p_vid and pid_norm in p_vid:
                still_open = True
                break
        if still_open:
            logger.warning(
                "reconcile_close WARN: position %s still visible in get_open_positions after close at %s",
                position_id, venue,
            )
        else:
            logger.info(
                "reconcile_close OK: position_id=%s no longer in open positions at %s",
                position_id, venue,
            )
    except Exception as e:
        logger.warning(
            "reconcile_close ERROR (best-effort, non-blocking): %s", e
        )
