"""
gTrade Backend REST Client

Implements read-only access to gTrade backend API:
- GET /open-trades/<address> - Get open positions
- GET /trading-variables - Get trading parameters (fees, funding, etc.)

No blockchain calls - pure HTTP REST.

References:
- https://docs.gains.trade/developer/integrators/backend
"""

from dataclasses import dataclass, field
from typing import Optional

import httpx

from foundation.logging import get_logger

from .config import get_gtrade_backend_url


logger = get_logger(__name__)


@dataclass(frozen=True)
class GTradeBackendClient:
    """
    gTrade backend REST client (read-only)

    Attributes:
        base_url: Backend API base URL (from MARKET_DATA_ENV / GTRADE_BACKEND_REST_URL)
        timeout_seconds: Request timeout (default: 5.0s)
    """
    base_url: str = field(default_factory=get_gtrade_backend_url)
    timeout_seconds: float = 5.0

    async def get_open_trades(self, address: str) -> dict:
        """
        Get open trades for wallet address

        Args:
            address: Wallet address (checksummed)

        Returns:
            Backend response dict (format may vary)

        Raises:
            httpx.HTTPError: On HTTP errors
            httpx.TimeoutException: On timeout
        """
        url = f"{self.base_url.rstrip('/')}/open-trades/{address}"

        logger.debug(f"Fetching open trades: {url}")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                logger.debug(f"Open trades response: {len(data) if isinstance(data, list) else 'unknown'} trades")
                return data

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching open trades: {e.response.status_code}")
                raise
            except httpx.TimeoutException as e:
                logger.error(f"Timeout fetching open trades: {e}")
                raise
            except Exception as e:
                logger.error(f"Error fetching open trades: {e}")
                raise

    async def get_trading_variables(self) -> dict:
        """
        Get trading variables (fees, funding rates, etc.)

        Returns:
            Trading variables dict

        Raises:
            httpx.HTTPError: On HTTP errors
            httpx.TimeoutException: On timeout
        """
        url = f"{self.base_url.rstrip('/')}/trading-variables"

        logger.debug(f"Fetching trading variables: {url}")

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                logger.debug("Trading variables fetched successfully")
                return data

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching trading variables: {e.response.status_code}")
                raise
            except httpx.TimeoutException as e:
                logger.error(f"Timeout fetching trading variables: {e}")
                raise
            except Exception as e:
                logger.error(f"Error fetching trading variables: {e}")
                raise
