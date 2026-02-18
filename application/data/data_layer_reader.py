"""
IDataLayerReader — abstracció per lectura de dades (OHLCV, coverage, data_status).

Split vNext Phase 2: trading_service pot consumir via HTTP (realtime_datalayer)
o local (candle_store). Implementacions: HttpDataLayerReader, LocalDataLayerReader.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

# LocalDataLayerReader usa lògica local de broker_routes (lazy import per evitar circular)


class IDataLayerReader(ABC):
    """Interfície per lectura de dades del Data Layer."""

    @abstractmethod
    def get_data_status(self) -> dict[str, Any]:
        """Retorna data_status (dict)."""
        ...

    @abstractmethod
    def get_coverage(self, symbol: str, resolution: str = "1m") -> dict[str, Any]:
        """Retorna coverage per símbol (dict)."""
        ...

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Optional[int] = None,
        to: Optional[int] = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Retorna (body_dict, headers_dict). headers inclou X-Data-*."""
        ...


class HttpDataLayerReader(IDataLayerReader):
    """Reader que consumeix realtime_datalayer via HTTP."""

    def __init__(self, client: Any):
        """client: RealtimeDataLayerClient."""
        self._client = client

    def get_data_status(self) -> dict[str, Any]:
        return self._client.get_data_status()

    def get_coverage(self, symbol: str, resolution: str = "1m") -> dict[str, Any]:
        return self._client.get_coverage(symbol=symbol, resolution=resolution)

    async def get_ohlcv(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Optional[int] = None,
        to: Optional[int] = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        return self._client.get_ohlcv(
            symbol=symbol, tf=tf, limit=limit, since=since, to=to
        )


class LocalDataLayerReader(IDataLayerReader):
    """
    Reader que usa la lògica local (candle_store, policy, etc.).
    Delega a broker_routes._local_* (lazy import).
    """

    def get_data_status(self) -> dict[str, Any]:
        from application.api.broker_routes import _local_compute_data_status
        return _local_compute_data_status()

    def get_coverage(self, symbol: str, resolution: str = "1m") -> dict[str, Any]:
        from application.api.broker_routes import _local_compute_coverage
        return _local_compute_coverage(symbol=symbol, resolution=resolution)

    async def get_ohlcv(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Optional[int] = None,
        to: Optional[int] = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        from application.api.broker_routes import _local_compute_ohlcv
        return await _local_compute_ohlcv(
            symbol=symbol, tf=tf, limit=limit, since=since, to=to
        )
