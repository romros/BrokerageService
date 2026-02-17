"""
P4.2 — Preflight per tests opt-in Lighter (xarxa)

Comprova que l'entorn està preparat per tests que requereixen Lighter API.
Si no → retorna (False, reason) per fer skip amb motiu clar, no fail amb "0 candles".

Ordre de comprovació:
1. Base URL accessible (timeout curt)
2. Candlestick endpoint retorna >= 1 candle (probe 2–3 min, EURUSD)

Ús:
  ok, reason = await preflight_lighter_candlestick()
  if not ok:
      print(f"SKIP: {reason}")
      sys.exit(2)  # run_all tracta exit 2 com a skipped
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

# Project root (testing/helpers/ -> testing/ -> project root)
ROOT = Path(__file__).resolve().parent.parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

PREFLIGHT_TIMEOUT_S = 3
PREFLIGHT_PROBE_MINUTES = 3
PREFLIGHT_SYMBOL_DEFAULT = "EURUSD"

# Exit code que run_all tracta com a "skipped" (no fail)
EXIT_SKIP = 2

# P7c.1: símbol per defecte segons entorn (mainnet: forex, testnet: crypto)
SOAK_SYMBOL_MAINNET = "EURUSD"
SOAK_SYMBOL_TESTNET = "ETH"


def select_soak_symbol(
    base_url: str,
    override: str | None = None,
) -> str:
    """
    P7c.1: Selecciona el símbol per el soak segons entorn.
    - override (env DATA_LAYER_SOAK_SYMBOL o --symbol): retorna el que diguis.
    - base_url conté "testnet" → ETH
    - Altrament → EURUSD
    """
    if override and override.strip():
        return override.strip().upper()
    url_lower = (base_url or "").lower()
    return SOAK_SYMBOL_TESTNET if "testnet" in url_lower else SOAK_SYMBOL_MAINNET


def _load_market_id_map() -> dict:
    raw = os.getenv("LIGHTER_MARKET_ID_MAP")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {"EURUSD": 96, "XAUUSD": 92, "XAU": 92}


async def preflight_lighter_candlestick(symbol: str | None = None) -> Tuple[bool, str]:
    """
    Preflight per Lighter Candlestick API.
    Returns (ok, reason). Si not ok, reason és el missatge de skip.
    symbol: símbol per provar (default PREFLIGHT_SYMBOL_DEFAULT). P7c.1: passar el que usarà el soak.
    """
    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").strip().rstrip("/")
    if not base_url:
        return False, "LIGHTER_BASE_URL not set"

    probe_symbol = (symbol or PREFLIGHT_SYMBOL_DEFAULT).strip().upper()
    market_id_map = _load_market_id_map()
    # P7c.1: si el símbol no està al map (ETH/BTC testnet), passar {} per forçar autodetect
    if probe_symbol not in market_id_map and probe_symbol not in {"XAU", "XAUUSD"}:
        market_id_map = {}

    try:
        from infrastructure.venues.lighter.lighter_candlestick_client import LighterCandlestickClient  # lazy: evita carregar Lighter si no es fa servir (P4.2 skip)

        now_ts = int(datetime.now(timezone.utc).timestamp())
        end_ts = (now_ts // 60) * 60
        start_ts = end_ts - (PREFLIGHT_PROBE_MINUTES * 60)

        client = LighterCandlestickClient(base_url=base_url, market_id_map=market_id_map)
        try:
            rows = await asyncio.wait_for(
                client.fetch_candles(probe_symbol, start_ts, end_ts),
                timeout=PREFLIGHT_TIMEOUT_S + 5,
            )
        finally:
            await client.close()

        if len(rows) < 1:
            env_hint = "testnet" if "testnet" in base_url.lower() else "mainnet"
            return False, f"LIGHTER Candlestick returned 0 candles (symbol={probe_symbol}, env={env_hint})"

        return True, ""

    except asyncio.TimeoutError:
        return False, "LIGHTER API unreachable (timeout)"
    except OSError as e:
        err = str(e).lower()
        if "connect" in err or "resolve" in err or "timeout" in err or "network" in err:
            return False, "LIGHTER API unreachable"
        return False, f"LIGHTER API error: {e}"
    except Exception as e:
        err = str(e).lower()
        if "connect" in err or "timeout" in err or "unreachable" in err:
            return False, "LIGHTER API unreachable"
        return False, f"LIGHTER Candlestick error: {e}"
