#!/usr/bin/env python3
"""
smoke_ostium_trade_cycle_testnet.py — Ostium TESTNET 1 OPEN + 1 CLOSE (opt-in, sense subgraph).

Executa un cicle real a testnet:
  1) Guardrails: OSTIUM_ENABLE_TX=1, OSTIUM_NETWORK=testnet, max collateral, leverage 2..20
  2) 1 OPEN market (via OstiumClient.open_trade)
  3) trade_index resolts pel client (getOpenTrade brute-force, sense subgraph)
  4) 1 CLOSE market (via OstiumClient.close_trade)
  5) Report PASS/FAIL + next_action

IMPORTANT: Només testnet. No imprimir private key ni raw tx. Timeout total 120s.
Refs: infrastructure/venues/ostium/ostium_client.py (canònic).
"""

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Mapes canònics (mateixos valors que infrastructure/venues/ostium); eviten import abans dels guardrails
SYMBOL_TO_PAIR_ID = {
    "EURUSD": 0, "XAUUSD": 1, "BTCUSD": 2, "ETHUSD": 3,
    "GBPUSD": 4, "GBPJPY": 5, "USDJPY": 6, "USDCHF": 7,
    "AUDUSD": 8, "USDCAD": 9,
}
PAIR_ID_TO_BASE_QUOTE = {
    0: ("EUR", "USD"), 1: ("XAU", "USD"), 2: ("BTC", "USD"), 3: ("ETH", "USD"),
    4: ("GBP", "USD"), 5: ("GBP", "JPY"), 6: ("USD", "JPY"), 7: ("USD", "CHF"),
    8: ("AUD", "USD"), 9: ("USD", "CAD"),
}

CYCLE_TIMEOUT_S = 120


# ── Model de resultat ─────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | INFO | SKIP
    category: str
    detail: str
    next_action: str = ""


results: list[CheckResult] = []


def _pass(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="PASS", category="OK", detail=detail)
    results.append(r)
    return r


def _fail(name: str, category: str, detail: str, next_action: str = "") -> CheckResult:
    r = CheckResult(
        name=name, status="FAIL", category=category,
        detail=detail, next_action=next_action,
    )
    results.append(r)
    return r


def _skip(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="SKIP", category="OK", detail=detail)
    results.append(r)
    return r


def _info(name: str, category: str, detail: str, next_action: str = "") -> CheckResult:
    r = CheckResult(
        name=name, status="INFO", category=category,
        detail=detail, next_action=next_action,
    )
    results.append(r)
    return r


# ── Guardrails (abans de network) ──────────────────────────────────────────────


def check_guardrails() -> dict | None:
    """
    Valida ENV i guardrails. Retorna dict de config si tot ok per executar; None si SKIP/FAIL.
    """
    print("\n[1] Guardrails Ostium trade-cycle (testnet)")

    if os.environ.get("OSTIUM_ENABLE_TX", "").strip() != "1":
        _skip(
            "ostium.tx.guard.enable_tx",
            "OSTIUM_ENABLE_TX no és 1 — smoke no executat",
        )
        return None

    _pass("ostium.tx.guard.enable_tx", "OSTIUM_ENABLE_TX=1")

    network = os.environ.get("OSTIUM_NETWORK", "").strip().lower()
    if network != "testnet":
        _fail(
            "ostium.tx.guard.network",
            "AUTH_INVALID_FORMAT",
            f"OSTIUM_NETWORK ha de ser 'testnet' (got {network!r})",
            next_action="Aquesta smoke només s’executa a testnet. Defineix OSTIUM_NETWORK=testnet",
        )
        return None

    _pass("ostium.tx.guard.network", "OSTIUM_NETWORK=testnet")

    pk = os.environ.get("OSTIUM_PRIVATE_KEY", "").strip()
    if not pk:
        _fail(
            "ostium.tx.guard.private_key",
            "AUTH_MISSING_ENV",
            "OSTIUM_PRIVATE_KEY absent",
            next_action="Afegeix OSTIUM_PRIVATE_KEY=0x... (64 hex) per signar TX a testnet",
        )
        return None
    if not re.match(r"^0x[0-9a-fA-F]{64}$", pk):
        _fail(
            "ostium.tx.guard.private_key",
            "AUTH_INVALID_FORMAT",
            "OSTIUM_PRIVATE_KEY format incorrecte (ha de ser 0x + 64 hex)",
            next_action="Format: 0x + 64 caràcters hex",
        )
        return None

    _pass("ostium.tx.guard.private_key", "OSTIUM_PRIVATE_KEY present (valor ocult)")

    symbol = os.environ.get("OSTIUM_MARKET_SYMBOL", "EURUSD").strip().upper()
    pair_id = SYMBOL_TO_PAIR_ID.get(symbol)
    if pair_id is None:
        known = ", ".join(SYMBOL_TO_PAIR_ID.keys())
        _fail(
            "ostium.tx.guard.symbol",
            "AUTH_INVALID_FORMAT",
            f"OSTIUM_MARKET_SYMBOL={symbol!r} desconegut. Coneguts: {known}",
            next_action=f"Usa un symbol vàlid: {known}",
        )
        return None

    base_quote = PAIR_ID_TO_BASE_QUOTE.get(pair_id)
    if not base_quote:
        _fail(
            "ostium.tx.guard.symbol",
            "AUTH_INVALID_FORMAT",
            f"pair_id={pair_id} sense base/quote definit",
            next_action="Usa OSTIUM_MARKET_SYMBOL=EURUSD (o altre conegut)",
        )
        return None

    _pass("ostium.tx.guard.symbol", f"OSTIUM_MARKET_SYMBOL={symbol} → pair_id={pair_id}")

    try:
        max_coll = float(os.environ.get("OSTIUM_MAX_COLLATERAL_USDC", "").strip())
    except (ValueError, TypeError):
        max_coll = -1.0
    if not (max_coll > 0):
        _fail(
            "ostium.tx.guard.max_collateral",
            "AUTH_MISSING_ENV",
            "OSTIUM_MAX_COLLATERAL_USDC absent o invàlid (ha de ser > 0)",
            next_action="Defineix OSTIUM_MAX_COLLATERAL_USDC=1 (guardrail màxim USDC)",
        )
        return None

    try:
        collateral = float(os.environ.get("OSTIUM_COLLATERAL_USDC", "").strip())
    except (ValueError, TypeError):
        collateral = -1.0
    if not (collateral > 0):
        _fail(
            "ostium.tx.guard.collateral",
            "AUTH_MISSING_ENV",
            "OSTIUM_COLLATERAL_USDC absent o invàlid (ha de ser > 0)",
            next_action="Defineix OSTIUM_COLLATERAL_USDC (ex: 0.5) <= OSTIUM_MAX_COLLATERAL_USDC",
        )
        return None

    if collateral > max_coll:
        _fail(
            "ostium.tx.guard.collateral",
            "AUTH_INVALID_FORMAT",
            f"OSTIUM_COLLATERAL_USDC={collateral} > OSTIUM_MAX_COLLATERAL_USDC={max_coll}",
            next_action="Redueix OSTIUM_COLLATERAL_USDC o augmenta OSTIUM_MAX_COLLATERAL_USDC",
        )
        return None

    _pass("ostium.tx.guard.collateral", f"collateral={collateral} USDC <= max={max_coll}")

    try:
        leverage = int(os.environ.get("OSTIUM_LEVERAGE", "").strip())
    except (ValueError, TypeError):
        leverage = -1
    if not (2 <= leverage <= 20):
        _fail(
            "ostium.tx.guard.leverage",
            "AUTH_INVALID_FORMAT",
            f"OSTIUM_LEVERAGE ha d’estar entre 2 i 20 (got {os.environ.get('OSTIUM_LEVERAGE', '')!r})",
            next_action="Defineix OSTIUM_LEVERAGE=5 (rang 2..20)",
        )
        return None

    _pass("ostium.tx.guard.leverage", f"OSTIUM_LEVERAGE={leverage}")

    close_price_mode = os.environ.get("OSTIUM_CLOSE_PRICE_MODE", "fresh").strip().lower()
    if close_price_mode not in ("fresh", "same"):
        _fail(
            "ostium.tx.guard.close_price_mode",
            "AUTH_INVALID_FORMAT",
            f"OSTIUM_CLOSE_PRICE_MODE ha de ser 'fresh' o 'same' (got {close_price_mode!r})",
            next_action="Defineix OSTIUM_CLOSE_PRICE_MODE=fresh o OSTIUM_CLOSE_PRICE_MODE=same",
        )
        return None
    _pass("ostium.tx.guard.close_price_mode", f"OSTIUM_CLOSE_PRICE_MODE={close_price_mode}")

    sleep_raw = os.environ.get("OSTIUM_POST_OPEN_SLEEP_S", "0").strip()
    if not sleep_raw:
        post_open_sleep_s = 0.0
    else:
        try:
            post_open_sleep_s = float(sleep_raw)
        except (ValueError, TypeError):
            post_open_sleep_s = -1.0
        if post_open_sleep_s < 0:
            _fail(
                "ostium.tx.guard.post_open_sleep",
                "AUTH_INVALID_FORMAT",
                f"OSTIUM_POST_OPEN_SLEEP_S ha de ser un nombre >= 0 (got {sleep_raw!r})",
                next_action="Defineix OSTIUM_POST_OPEN_SLEEP_S=0 o un nombre positiu (segons)",
            )
            return None
    if post_open_sleep_s > 0:
        _pass("ostium.tx.guard.post_open_sleep", f"OSTIUM_POST_OPEN_SLEEP_S={post_open_sleep_s}s")

    is_long_str = os.environ.get("OSTIUM_IS_LONG", "true").strip().lower()
    is_long = is_long_str in ("1", "true", "yes")

    rpc_url = os.environ.get("OSTIUM_RPC_URL", "").strip() or None

    return {
        "private_key": pk,
        "network": "testnet",
        "rpc_url": rpc_url,
        "symbol": symbol,
        "pair_id": pair_id,
        "base_quote": base_quote,
        "collateral": collateral,
        "leverage": leverage,
        "is_long": is_long,
        "close_price_mode": close_price_mode,
        "post_open_sleep_s": post_open_sleep_s,
    }


# ── Execució 1 OPEN + 1 CLOSE ─────────────────────────────────────────────────


def _category_from_exception(e: BaseException) -> str:
    msg = str(e).lower()
    if "revert" in msg or "execution" in msg:
        return "CONTRACT_REVERT"
    if "timeout" in msg or "timed out" in msg:
        return "CONNECT_TIMEOUT"
    if "connection refused" in msg:
        return "CONNECT_REFUSED"
    if "gaierror" in type(e).__name__.lower() or "dns" in msg:
        return "DNS"
    return "SDK_ERROR"


async def _run_cycle(cfg: dict) -> None:
    """1 OPEN + 1 CLOSE. Reporta resultats a la llista global results. Import canònic aquí (després dels guardrails)."""
    ROOT = Path(__file__).resolve().parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from infrastructure.venues.ostium.ostium_client import OstiumClient

    client = OstiumClient(
        private_key=cfg["private_key"],
        network=cfg["network"],
        rpc_url=cfg["rpc_url"],
    )
    client._ensure_sdk()
    trader = client._trader_address
    pair_id = cfg["pair_id"]
    base, quote = cfg["base_quote"]
    collateral = cfg["collateral"]
    leverage = cfg["leverage"]
    is_long = cfg["is_long"]

    print(f"\n[2] Preu i OPEN (pair_id={pair_id}, symbol={cfg['symbol']})")
    print(f"    trader={trader[:10]}...{trader[-6:]}")

    try:
        mid, _, _ = await client.get_price(base, quote)
    except Exception as e:
        _fail(
            "ostium.tx.price",
            _category_from_exception(e),
            f"get_price({base},{quote}) fallat: {e!s}",
            next_action="Comprova RPC i connectivitat (OSTIUM_RPC_URL)",
        )
        return

    _pass("ostium.tx.price", f"mid={mid} ({base}/{quote})")

    try:
        receipt_open = await client.open_trade(
            pair_id=pair_id,
            is_long=is_long,
            collateral=collateral,
            leverage=leverage,
            at_price=mid,
            tp_price=0.0,
            sl_price=0.0,
        )
    except Exception as e:
        _fail(
            "ostium.tx.open",
            _category_from_exception(e),
            f"open_trade fallat: {e!s}",
            next_action="Revisa saldo USDC, leverage, contract i RPC (testnet)",
        )
        return

    tx_open_prefix = (receipt_open.tx_hash or "")[:18]
    _pass(
        "ostium.tx.open",
        f"tx={tx_open_prefix}... pair_id={receipt_open.pair_id} trade_index={receipt_open.trade_index}",
    )

    sleep_s = cfg.get("post_open_sleep_s", 0) or 0
    if sleep_s > 0:
        await asyncio.sleep(sleep_s)
        _pass("ostium.tx.sleep", f"slept {sleep_s}s")

    print(f"\n[3] CLOSE (pair_id={receipt_open.pair_id}, trade_index={receipt_open.trade_index})")

    close_price_mode = cfg.get("close_price_mode", "fresh")
    mid_close = mid
    if close_price_mode == "fresh":
        try:
            mid_close, _, _ = await client.get_price(base, quote)
            _pass("ostium.tx.close_price", f"fresh mid={mid_close} ({base}/{quote})")
        except Exception:
            _info(
                "ostium.tx.close_price",
                "OK",
                "get_price failed, fallback to open mid",
                next_action="",
            )
            mid_close = mid
    else:
        _pass("ostium.tx.close_price", "same (reuse open mid)")

    try:
        receipt_close = await client.close_trade(
            pair_id=receipt_open.pair_id,
            trade_index=receipt_open.trade_index,
            at_price=mid_close,
        )
    except Exception as e:
        _fail(
            "ostium.tx.close",
            _category_from_exception(e),
            f"close_trade fallat: {e!s}",
            next_action="Revisa contract i RPC; el trade pot estar ja tancat",
        )
        return

    tx_close_prefix = (receipt_close.tx_hash or "")[:18]
    _pass("ostium.tx.close", f"tx={tx_close_prefix}...")


# ── Report ────────────────────────────────────────────────────────────────────


def print_report() -> int:
    pass_n = sum(1 for r in results if r.status == "PASS")
    fail_n = sum(1 for r in results if r.status == "FAIL")
    skip_n = sum(1 for r in results if r.status == "SKIP")

    print()
    print("─" * 60)
    print("  REPORT — smoke_ostium_trade_cycle_testnet")
    print("─" * 60)
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "INFO": "ℹ", "SKIP": "⊘"}.get(r.status, "?")
        line = f"  {icon} [{r.status}] {r.name}"
        if r.category != "OK":
            line += f"  [{r.category}]"
        if r.detail:
            line += f"  — {r.detail}"
        print(line)
        if r.status in ("FAIL", "INFO") and r.next_action:
            print(f"       → {r.next_action}")
    print("─" * 60)
    print(f"  Resultat: {pass_n} PASS, {fail_n} FAIL, {skip_n} SKIP")
    print("─" * 60)
    return 0 if fail_n == 0 else 1


# ── Main ─────────────────────────────────────────────────────────────────────


async def main_async() -> int:
    print("── smoke_ostium_trade_cycle_testnet.py ─────────────────────")
    print("   1 OPEN + 1 CLOSE a testnet (sense subgraph)")
    print(f"   Timeout cicle: {CYCLE_TIMEOUT_S}s")

    cfg = check_guardrails()
    if cfg is None:
        return print_report()

    try:
        await asyncio.wait_for(_run_cycle(cfg), timeout=CYCLE_TIMEOUT_S)
    except asyncio.TimeoutError:
        _fail(
            "ostium.tx.cycle",
            "CONNECT_TIMEOUT",
            f"Cicle no ha acabat en {CYCLE_TIMEOUT_S}s",
            next_action="Augmenta connectivitat o redueix retries al client",
        )

    return print_report()


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
