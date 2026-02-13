"""
Helpers compartits per lectura de candles (reutilitzats per broker_routes).

Evita duplicar la lògica read_range entre /broker/ohlcv i /broker/candles.
"""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from domain.models import CandleRange


def resolve_candle_range(
    end: datetime,
    limit: int,
    since_epoch: Optional[int] = None,
    to_epoch: Optional[int] = None,
    tz: ZoneInfo = ZoneInfo("America/New_York"),
) -> tuple[datetime, datetime]:
    """
    Resol start/end per a lectura de candles.

    Args:
        end: Data fi (tz-aware)
        limit: Màxim de candles (minuts)
        since_epoch: Opcional; start en epoch seconds
        to_epoch: Opcional; end en epoch seconds (sobreescriu end)
        tz: Timezone per since/to

    Returns:
        (start, end) tz-aware
    """
    if to_epoch is not None:
        end = datetime.fromtimestamp(to_epoch, tz=tz)
    if since_epoch is not None:
        start = datetime.fromtimestamp(since_epoch, tz=tz)
    else:
        start = end - timedelta(minutes=limit)

    total_minutes = int((end - start).total_seconds() / 60)
    if total_minutes > limit:
        start = end - timedelta(minutes=limit)
    return start, end


def read_candles(
    store,
    symbol: str,
    start: datetime,
    end: datetime,
    validate_gaps: bool = False,
) -> CandleRange:
    """Llegeix candles del store. Delegació directa."""
    return store.read_range(
        symbol=symbol,
        start=start,
        end=end,
        validate_gaps=validate_gaps,
    )
