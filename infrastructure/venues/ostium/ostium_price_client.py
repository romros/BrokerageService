"""
Ostium REST Price Client — fetch latest price per symbol.

API: https://metadata-backend.ostium.io/PricePublish/latest-price?asset=SYMBOL
Returns: {"mid": 1.123, "bid": ..., "ask": ..., "timestampSeconds": 1234567890}
"""

import os
import time
from typing import Optional

from foundation.config.constants import (
    OSTIUM_PRICE_API_BASE_ENV,
    DEFAULT_OSTIUM_PRICE_API_BASE,
)

try:
    import requests
except ImportError:
    requests = None

MAX_RETRIES = 3
RETRY_BACKOFF_S = [1, 2, 4]
TIMEOUT_S = 10


def fetch_latest_price(symbol: str) -> Optional[dict]:
    """
    Fetch latest price from Ostium REST API.

    Returns:
        {"price": float, "timestamp": int} or None if error
    """
    if requests is None:
        return None
    base = os.getenv(OSTIUM_PRICE_API_BASE_ENV, DEFAULT_OSTIUM_PRICE_API_BASE).rstrip("/")
    url = f"{base}/PricePublish/latest-price"
    params = {"asset": symbol}

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_S)
            if response.status_code == 200:
                data = response.json()
                price = float(data.get("mid", 0))
                ts = int(data.get("timestampSeconds", time.time()))
                return {"price": price, "timestamp": ts}
            if response.status_code == 429:
                backoff = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                time.sleep(backoff)
                continue
            return None
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_S[attempt])
            return None
    return None
