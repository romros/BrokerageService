"""
Lighter Candlestick API client (P4.0)

Fetches 1m candles via Lighter Candlestick API.
- Paginator ≤500 per request
- Sleep 1.05s between requests (rate limit ~60/min)
- Retry 429 with backoff
- Brotli fallback: httpx amb Accept-Encoding: identity

References: lab/lighter/scripts/fetch_historical_candles.py, coverage_probe.py
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from foundation.logging import get_logger

logger = get_logger(__name__)

CHUNK_LIMIT = 500
RESOLUTION = "1m"
MIN_SLEEP_BETWEEN_REQ = 1.05
RETRY_DELAY = 1.0
MAX_RETRIES = 3

SYMBOL_NORMALIZE = {"XAU": "XAUUSD", "EURUSD": "EURUSD", "ETH": "ETH", "BTC": "BTC"}


def _normalize_symbol(s: str) -> str:
    return SYMBOL_NORMALIZE.get(s.upper(), s.upper())


def _ts_to_start_of_minute(ts: int) -> int:
    return (ts // 60) * 60


def _parse_candle(c, symbol_canonical: str) -> dict:
    """Parse Lighter candle to canonical dict. ts = start-of-minute UTC."""
    def _get(obj, *keys):
        for k in keys:
            if isinstance(obj, dict):
                v = obj.get(k)
            else:
                v = getattr(obj, k, None)
            if v is not None:
                return v
        return None
    t_raw = int(_get(c, "t", "T") or 0)
    ts_s = t_raw // 1000 if t_raw > 1e12 else t_raw
    ts = _ts_to_start_of_minute(ts_s)
    o = float(_get(c, "o", "O") or 0)
    h = float(_get(c, "h", "H") or 0)
    l_ = float(_get(c, "l", "L") or 0)
    c_ = float(_get(c, "c", "C") or 0)
    v = float(_get(c, "v", "V") or 0)
    return {
        "ts": ts,
        "open": o,
        "high": h,
        "low": l_,
        "close": c_,
        "volume": v if v >= 0 else 0,
        "symbol": symbol_canonical,
    }


def _load_market_id_map() -> Dict[str, int]:
    raw = os.getenv("LIGHTER_MARKET_ID_MAP")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


async def _autodetect_market_ids(base_url: str) -> Dict[str, int]:
    """Autodetect symbol→market_id via OrderApi.order_books()."""
    import lighter  # lazy: evita carregar lighter SDK si no es fa servir candlestick
    cfg = lighter.Configuration(host=base_url)
    client = lighter.ApiClient(cfg)
    try:
        orders_api = lighter.OrderApi(client)
        resp = await orders_api.order_books()
        await client.close()
    except Exception as e:
        await client.close()
        raise RuntimeError(f"Autodetect order_books failed: {e}") from e

    result = {}
    for ob in getattr(resp, "order_books", []) or []:
        mid = getattr(ob, "market_id", None)
        sym = getattr(ob, "symbol", None)
        if mid is not None and sym:
            s = str(sym).upper().replace("-USDC", "").replace("-", "").replace("/", "")
            result[s] = mid
            if "XAU" in s:
                result["XAU"] = mid
                result["XAUUSD"] = mid
            elif "EUR" in s:
                result["EURUSD"] = mid
            elif "ETH" in s or s == "WETH":
                result["ETH"] = mid
            elif "BTC" in s:
                result["BTC"] = mid
    return result


async def _fetch_one_sdk(
    candlestick_api,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
    symbol_canonical: str,
) -> List[dict]:
    candles_obj = await candlestick_api.candles(
        market_id=market_id,
        resolution=RESOLUTION,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        count_back=count_back,
    )
    items = getattr(candles_obj, "c", []) or []
    return [_parse_candle(c, symbol_canonical) for c in items]


async def _fetch_one_httpx(
    base_url: str,
    market_id: int,
    start_ts: int,
    end_ts: int,
    count_back: int,
    symbol_canonical: str,
) -> List[dict]:
    """Fallback: httpx amb Accept-Encoding: identity (evita brotli)."""
    import httpx  # lazy: evita carregar httpx si es fa servir SDK
    url = f"{base_url.rstrip('/')}/api/v1/candles"
    params = {
        "market_id": market_id,
        "resolution": RESOLUTION,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "count_back": count_back,
    }
    headers = {"Accept-Encoding": "identity"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    items = data.get("c", []) or []
    return [_parse_candle(obj, symbol_canonical) for obj in items]


class LighterCandlestickClient:
    """
    Client per Lighter Candlestick API.
    Paginació ≤500, sleep 1.05s, retry 429, brotli fallback.
    """

    def __init__(
        self,
        base_url: str,
        market_id_map: Optional[Dict[str, int]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._market_id_map = market_id_map or _load_market_id_map()
        self._sdk_client = None
        self._candlestick_api = None

    async def _ensure_market_ids(self) -> None:
        if self._market_id_map:
            return
        self._market_id_map = await _autodetect_market_ids(self.base_url)
        logger.info("LighterCandlestickClient: autodetected market_ids %s", self._market_id_map)

    def _get_market_id(self, symbol: str) -> int:
        sym = symbol.upper()
        canonical = _normalize_symbol(symbol)
        mid = self._market_id_map.get(sym) or self._market_id_map.get(canonical)
        if mid is None:
            raise ValueError(f"market_id not found for {symbol}")
        return mid

    async def fetch_candles(
        self,
        symbol: str,
        start_ts: int,
        end_ts: int,
    ) -> List[dict]:
        """
        Fetch candles [start_ts, end_ts) (end exclusive).
        Returns list of dicts {ts, open, high, low, close, volume, symbol}.
        Deduplicated by ts, sorted.
        """
        await self._ensure_market_ids()
        market_id = self._get_market_id(symbol)
        symbol_canonical = _normalize_symbol(symbol)

        # Lazy init SDK
        if self._candlestick_api is None:
            import lighter  # lazy: evita carregar lighter SDK fins al primer fetch
            cfg = lighter.Configuration(host=self.base_url)
            self._sdk_client = lighter.ApiClient(cfg)
            self._candlestick_api = lighter.CandlestickApi(self._sdk_client)

        all_candles: List[dict] = []
        current_start = start_ts

        while current_start < end_ts:
            chunk_end = min(current_start + CHUNK_LIMIT * 60, end_ts)
            chunk_items: List[dict] = []
            for attempt in range(MAX_RETRIES):
                try:
                    chunk_items = await _fetch_one_sdk(
                        self._candlestick_api,
                        market_id,
                        current_start,
                        chunk_end,
                        CHUNK_LIMIT,
                        symbol_canonical,
                    )
                    break
                except Exception as e:
                    if "429" in str(e) or "rate" in str(e).lower():
                        await asyncio.sleep(RETRY_DELAY * (attempt + 2))
                    elif ("br" in str(e).lower() or "content-encoding" in str(e).lower()) and attempt == 0:
                        try:
                            chunk_items = await _fetch_one_httpx(
                                self.base_url,
                                market_id,
                                current_start,
                                chunk_end,
                                CHUNK_LIMIT,
                                symbol_canonical,
                            )
                            break
                        except Exception:
                            pass
                    if attempt == MAX_RETRIES - 1:
                        raise
            for row in chunk_items:
                if start_ts <= row["ts"] < end_ts:
                    all_candles.append(row)
            current_start = chunk_end
            await asyncio.sleep(MIN_SLEEP_BETWEEN_REQ)

        # Dedup by ts, sort
        by_ts: Dict[int, dict] = {}
        for row in all_candles:
            by_ts[row["ts"]] = row
        return sorted(by_ts.values(), key=lambda x: x["ts"])

    async def close(self) -> None:
        if self._sdk_client is not None:
            try:
                await self._sdk_client.close()
            except Exception:
                pass
            self._sdk_client = None
            self._candlestick_api = None
