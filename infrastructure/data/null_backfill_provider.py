"""
NullBackfillProvider — Provider no-op per realtime_datalayer.

El realtime_datalayer és independent de Dukascopy (AGENTS_ARQUITECTURA).
Ostium escriu al store; DataLayerProdService només executa gate metrics loop.
"""

from datetime import datetime
from typing import List

from domain.interfaces import IBackfillProvider
from domain.models import Candle


class NullBackfillProvider(IBackfillProvider):
    """
    Provider que no fa backfill. is_available() = False.

    Usat per realtime_datalayer: Ostium és l'únic writer; no cal Dukascopy.
    """

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        return []

    async def is_available(self) -> bool:
        return False

    @property
    def provider_name(self) -> str:
        return "null"

    @property
    def max_range_minutes(self) -> int:
        return 0
