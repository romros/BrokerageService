#!/usr/bin/env python3
"""
Explorador — Candles via BrokerageService (Docker / broker en marxa)

Explora com obtenir dades OHLCV des del broker (pipeline → store → API).
Funciona dins Docker (brokerage:8000) o des de host (localhost:8000).

Ús:
  # Dins lighter-lab (broker en marxa a la mateixa xarxa):
  docker compose run --rm lighter-lab python3 lab/lighter/scripts/explore_broker_candles.py

  # Des de host (broker a localhost:8000):
  BROKER_URL=http://localhost:8000 python3 lab/lighter/scripts/explore_broker_candles.py

  # Amb símbols concrets:
  python3 lab/lighter/scripts/explore_broker_candles.py --symbol EURUSD --symbol XAUUSD
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

DEFAULT_BROKER_URL = os.getenv("BROKER_URL", "http://brokerage:8000")
DEFAULT_SYMBOLS = ["EURUSD", "XAUUSD"]


def _get(url: str, params: dict | None = None, timeout: int = 15) -> requests.Response:
    r = requests.get(url, params=params or {}, timeout=timeout)
    return r


def explore_health(base_url: str) -> bool:
    """Comprova que el broker respon."""
    try:
        r = _get(f"{base_url}/api/v1/broker/health")
        if r.status_code != 200:
            print(f"  ✗ Health {r.status_code}")
            return False
        data = r.json()
        print(f"  ✓ Health: {data.get('status', '?')} mode={data.get('mode')} venue={data.get('venue')}")
        return True
    except Exception as e:
        print(f"  ✗ Health error: {e}")
        return False


def explore_ohlcv(base_url: str, symbol: str, limit: int = 10) -> None:
    """Explora GET /ohlcv/{symbol} i headers X-Data-*."""
    url = f"{base_url}/api/v1/broker/ohlcv/{symbol}"
    try:
        r = _get(url, params={"limit": limit})
        print(f"\n  GET /ohlcv/{symbol}?limit={limit} → {r.status_code}")
        if r.status_code != 200:
            print(f"    Body: {r.text[:200]}")
            return

        # Headers P5 (Data Observability)
        headers_p5 = [k for k in r.headers if k.lower().startswith("x-data-")]
        if headers_p5:
            print("    Headers X-Data-*:")
            for k in sorted(headers_p5):
                print(f"      {k}: {r.headers[k]}")
        else:
            print("    (no X-Data-* headers)")

        data = r.json()
        count = data.get("count", 0)
        candles = data.get("candles", [])
        print(f"    count={count} is_complete={data.get('is_complete')} missing_count={data.get('missing_count', 0)}")
        if candles:
            c0 = candles[0]
            print(f"    Primer candle: ts={c0.get('ts')} O={c0.get('open')} H={c0.get('high')} L={c0.get('low')} C={c0.get('close')} V={c0.get('volume')}")
    except Exception as e:
        print(f"    Error: {e}")


def explore_candles(base_url: str, symbol: str, limit: int = 5) -> None:
    """Explora GET /candles?symbol=... (query param)."""
    url = f"{base_url}/api/v1/broker/candles"
    try:
        r = _get(url, params={"symbol": symbol, "limit": limit})
        print(f"\n  GET /candles?symbol={symbol}&limit={limit} → {r.status_code}")
        if r.status_code != 200:
            return
        data = r.json()
        print(f"    count={data.get('count')} symbol={data.get('symbol')}")
    except Exception as e:
        print(f"    Error: {e}")


def explore_coverage(base_url: str, symbol: str) -> None:
    """Explora GET /coverage?symbol=... (P5 Data Observability)."""
    url = f"{base_url}/api/v1/broker/coverage"
    try:
        r = _get(url, params={"symbol": symbol, "resolution": "1m"})
        print(f"\n  GET /coverage?symbol={symbol}&resolution=1m → {r.status_code}")
        if r.status_code != 200:
            print(f"    Body: {r.text[:300]}")
            return
        data = r.json()
        print(f"    earliest_ts: {data.get('earliest_ts')}")
        print(f"    latest_ts: {data.get('latest_ts')}")
        print(f"    source: {data.get('source')}")
        w = data.get("window_72h", {})
        if w:
            print(f"    window_72h: expected={w.get('expected_minutes')} candles={w.get('candles')} missing={w.get('missing_minutes')} max_gap_s={w.get('max_gap_s')}")
    except Exception as e:
        print(f"    Error: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Explorador candles via BrokerageService")
    parser.add_argument("--broker-url", default=DEFAULT_BROKER_URL, help="Broker base URL")
    parser.add_argument("--symbol", action="append", default=[], help="Symbols (default: EURUSD XAUUSD)")
    parser.add_argument("--limit", type=int, default=10, help="Limit candles per request")
    args = parser.parse_args()

    symbols = args.symbol if args.symbol else DEFAULT_SYMBOLS
    base = args.broker_url.rstrip("/")

    print("=" * 60)
    print("Explorador — Candles via BrokerageService")
    print("=" * 60)
    print(f"  BROKER_URL: {base}")
    print(f"  Symbols: {symbols}")
    print()

    if not explore_health(base):
        print("\n  El broker no respon. Assegura't que:")
        print("    - docker compose up -d brokerage  (broker en marxa)")
        print("    - Dins Docker: BROKER_URL=http://brokerage:8000")
        print("    - Des de host: BROKER_URL=http://localhost:8000")
        return 1

    for symbol in symbols:
        print(f"\n--- {symbol} ---")
        explore_ohlcv(base, symbol, args.limit)
        explore_candles(base, symbol, min(5, args.limit))
        explore_coverage(base, symbol)

    print("\n" + "=" * 60)
    print("  Flux: pipeline (WS/REST) → candle_store (CSV) → API /ohlcv, /candles, /coverage")
    print("  Headers X-Data-*: P5 Data Observability (source, coverage, gaps, repair)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
