"""
RealtimeDataLayerClient — HTTP client per consumir contracte mínim del realtime_datalayer.

Split vNext Phase 2: trading_service consumeix OHLCV/coverage/data_status via HTTP.
Timeouts curts; errors tipats.
"""

import os
from typing import Any, Optional

import httpx

from foundation.config.constants import (
    REALTIME_DATALAYER_BASE_URL_ENV,
    DEFAULT_REALTIME_DATALAYER_TIMEOUT_S,
)

# Path prefix del broker API (realtime_datalayer exposa /api/v1/broker)
BROKER_API_PREFIX = "/api/v1/broker"


class RealtimeDataLayerError(Exception):
    """Error en comunicar amb realtime_datalayer."""


class RealtimeDataLayerClient:
    """
    Client HTTP per contracte mínim realtime_datalayer.
    Mètodes: get_data_status, get_coverage, get_ohlcv.
    """

    def __init__(
        self,
        base_url: str,
        timeout_s: float = DEFAULT_REALTIME_DATALAYER_TIMEOUT_S,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_data_status(self) -> dict[str, Any]:
        """GET /api/v1/broker/data_status. Retorna dict (JSON body)."""
        url = self._url(f"{BROKER_API_PREFIX}/data_status")
        try:
            r = httpx.get(url, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise RealtimeDataLayerError(f"data_status {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RealtimeDataLayerError(f"data_status request failed: {e}") from e

    def get_coverage(self, symbol: str, resolution: str = "1m") -> dict[str, Any]:
        """GET /api/v1/broker/coverage. Retorna dict (JSON body)."""
        url = self._url(f"{BROKER_API_PREFIX}/coverage")
        params = {"symbol": symbol, "resolution": resolution}
        try:
            r = httpx.get(url, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise RealtimeDataLayerError(f"coverage {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RealtimeDataLayerError(f"coverage request failed: {e}") from e

    def get_ohlcv(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Optional[int] = None,
        to: Optional[int] = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """
        GET /api/v1/broker/ohlcv/{symbol}.
        Retorna (body_dict, headers_dict).
        headers_dict inclou X-Data-* per transparència.
        """
        url = self._url(f"{BROKER_API_PREFIX}/ohlcv/{symbol}")
        params = {"tf": tf, "limit": limit}
        if since is not None:
            params["since"] = since
        if to is not None:
            params["to"] = to
        try:
            r = httpx.get(url, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            body = r.json()
            # Copiar headers X-Data-* per transparència
            headers = {}
            for k, v in r.headers.items():
                if k.lower().startswith("x-data-"):
                    headers[k] = v
            return body, headers
        except httpx.HTTPStatusError as e:
            raise RealtimeDataLayerError(f"ohlcv {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RealtimeDataLayerError(f"ohlcv request failed: {e}") from e


def get_realtime_datalayer_client_from_env() -> Optional[RealtimeDataLayerClient]:
    """Crea client si REALTIME_DATALAYER_BASE_URL està set; altrament None."""
    base_url = os.getenv(REALTIME_DATALAYER_BASE_URL_ENV, "").strip()
    if not base_url:
        return None
    return RealtimeDataLayerClient(base_url=base_url)
