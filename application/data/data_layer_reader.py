"""
IDataLayerReader — abstracció per lectura de dades (OHLCV, coverage, data_status).

Split vNext Phase 2: trading_service pot consumir via HTTP (realtime_datalayer)
o local (candle_store). Implementacions: HttpDataLayerReader, LocalDataLayerReader.

get_ohlcv_with_gate: retorna (body, headers, QualityGateResult).
El gate avalua X-Data-* headers fail-closed; NEVER throws.
El caller (trading loop) aplica NO_TRADE si gate.is_bad().
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

from foundation.config.constants import (
    DEFAULT_QUALITY_GATE_MAX_FRESHNESS_SEC,
    DEFAULT_QUALITY_GATE_MAX_GAP_S,
    DEFAULT_QUALITY_GATE_MIN_COMPLETENESS,
    QUALITY_GATE_MAX_FRESHNESS_SEC_ENV,
    QUALITY_GATE_MAX_GAP_S_ENV,
    QUALITY_GATE_MIN_COMPLETENESS_ENV,
)

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

    async def get_ohlcv_with_gate(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Optional[int] = None,
        to: Optional[int] = None,
    ) -> "tuple[dict[str, Any], dict[str, str], Any]":
        """
        get_ohlcv + quality gate avaluació.
        Retorna (body, headers, QualityGateResult).
        NEVER throws per gate BAD; el caller decideix NO_TRADE si gate.is_bad().
        """
        from application.data.quality_gate import evaluate_quality_gate

        body, headers = await self.get_ohlcv(symbol=symbol, tf=tf, limit=limit, since=since, to=to)
        gate = evaluate_quality_gate(
            headers=headers,
            candles_count=len(body.get("candles", [])),
            max_freshness_sec=int(os.getenv(QUALITY_GATE_MAX_FRESHNESS_SEC_ENV, str(DEFAULT_QUALITY_GATE_MAX_FRESHNESS_SEC))),
            min_completeness=float(os.getenv(QUALITY_GATE_MIN_COMPLETENESS_ENV, str(DEFAULT_QUALITY_GATE_MIN_COMPLETENESS))),
            max_gap_s=int(os.getenv(QUALITY_GATE_MAX_GAP_S_ENV, str(DEFAULT_QUALITY_GATE_MAX_GAP_S))),
        )
        return body, headers, gate


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
