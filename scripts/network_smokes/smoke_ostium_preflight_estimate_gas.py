#!/usr/bin/env python3
"""
smoke_ostium_preflight_estimate_gas.py — Ostium preflight estimateGas only (0 signing, 0 send, opt-in).

Valida que una TX (calldata) seria estimable via eth_estimateGas sense enviar res:
  1. ENV vars (OSTIUM_RPC_URL, OSTIUM_CONTRACT_ADDRESS, OSTIUM_FROM_ADDRESS; OSTIUM_CHAIN_ID opcional)
  2. Chain guard (eth_chainId vs OSTIUM_CHAIN_ID si present)
  3. eth_estimateGas amb {from, to, data, value=0}
     - Calldata: reutilitzada de smoke_ostium_preflight_call.build_get_open_trade_calldata (NO inventar)
     - PASS si result hex; FAIL CONTRACT_REVERT si error

Categories: AUTH_MISSING_ENV, AUTH_INVALID_FORMAT, DNS, CONNECT_TIMEOUT, CONNECT_REFUSED,
  CHAIN_MISMATCH, CONTRACT_REVERT, UNEXPECTED_PAYLOAD.

Check names: ostium.eg.env.*, ostium.eg.rpc.chain_id, ostium.eg.rpc.estimate_gas.

IMPORTANT: No signa, no envia cap TX. No secrets en logs. Timeout 5s.
"""

import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# Calldata: reutilitzar funció existent (no inventar ABI)
from smoke_ostium_preflight_call import (
    CHAIN_IDS,
    SYMBOL_TO_PAIR_ID,
    build_get_open_trade_calldata,
)

TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "5"))


# ── Model de resultat ─────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str
    category: str
    detail: str
    next_action: str = ""


results: list[CheckResult] = []


def _pass(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="PASS", category="OK", detail=detail)
    results.append(r)
    return r


def _fail(name: str, category: str, detail: str, next_action: str = "") -> CheckResult:
    r = CheckResult(name=name, status="FAIL", category=category,
                    detail=detail, next_action=next_action)
    results.append(r)
    return r


def _info(name: str, category: str, detail: str, next_action: str = "") -> CheckResult:
    r = CheckResult(name=name, status="INFO", category=category,
                    detail=detail, next_action=next_action)
    results.append(r)
    return r


def _skip(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="SKIP", category="OK", detail=detail)
    results.append(r)
    return r


def _net_category(reason: str) -> str:
    r = reason.lower()
    if "timed out" in r or "timeout" in r:
        return "CONNECT_TIMEOUT"
    if "connection refused" in r:
        return "CONNECT_REFUSED"
    return "CONNECT_TIMEOUT"


def _net_next(cat: str) -> str:
    if cat == "DNS":
        return "Comprova DNS, proxy, VPN o si el host és accessible"
    if cat == "CONNECT_TIMEOUT":
        return f"Timeout ({TIMEOUT}s) — comprova que el RPC sigui accessible"
    if cat == "CONNECT_REFUSED":
        return "Connexió refusada — comprova la URL del RPC"
    return "Comprova connectivitat de xarxa"


# ── JSON-RPC ──────────────────────────────────────────────────────────────────


def _jsonrpc_simple(rpc_url: str, method: str, params: list) -> tuple[Optional[object], Optional[str]]:
    """Crida JSON-RPC genèrica (eth_chainId, etc.). Error → UNEXPECTED_PAYLOAD."""
    parsed = urlparse(rpc_url)
    host = parsed.hostname or ""
    try:
        socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, "DNS"
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    try:
        req = urllib.request.Request(
            rpc_url, data=payload, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "BrokerageService-NetworkSmoke/1.0"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            d = json.loads(resp.read())
            if "error" in d:
                return None, "UNEXPECTED_PAYLOAD"
            return d.get("result"), None
    except urllib.error.HTTPError as e:
        return None, "HTTP_4XX" if e.code < 500 else "HTTP_5XX"
    except urllib.error.URLError as e:
        return None, _net_category(str(e.reason))
    except (TimeoutError, json.JSONDecodeError):
        return None, "CONNECT_TIMEOUT"


def _jsonrpc_estimate_gas(
    rpc_url: str,
    from_addr: str,
    to_addr: str,
    data_hex: str,
    value_hex: str = "0x0",
) -> tuple[Optional[str], Optional[str]]:
    """eth_estimateGas amb from, to, data, value. Retorna (result_hex, error_category). CONTRACT_REVERT si revert."""
    parsed = urlparse(rpc_url)
    host = parsed.hostname or ""
    try:
        socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, "DNS"
    params = [{"from": from_addr, "to": to_addr, "data": data_hex, "value": value_hex}]
    payload = json.dumps({"jsonrpc": "2.0", "method": "eth_estimateGas", "params": params, "id": 1}).encode()
    try:
        req = urllib.request.Request(
            rpc_url, data=payload, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "BrokerageService-NetworkSmoke/1.0"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            d = json.loads(resp.read())
            if "error" in d:
                err = d["error"]
                code = err.get("code", 0)
                msg = err.get("message", "")
                if code in (-32000, -32015) or "revert" in msg.lower() or "execution" in msg.lower():
                    return None, f"CONTRACT_REVERT:{msg[:120]}"
                return None, f"UNEXPECTED_PAYLOAD:{msg[:80]}"
            return d.get("result"), None
    except urllib.error.HTTPError as e:
        return None, "HTTP_4XX" if e.code < 500 else "HTTP_5XX"
    except urllib.error.URLError as e:
        return None, _net_category(str(e.reason))
    except (TimeoutError, json.JSONDecodeError):
        return None, "CONNECT_TIMEOUT"


# ── Secció 1: ENV vars ────────────────────────────────────────────────────────


def check_env() -> dict:
    """
    Valida ENV. Retorna dict amb rpc_url, chain_id_expected, contract, from_address, pair_id.
    OSTIUM_CONTRACT_ADDRESS i OSTIUM_FROM_ADDRESS obligatoris sense default (aquest smoke).
    """
    print("\n[1] ENV vars Ostium estimateGas preflight")

    out: dict = {
        "rpc_url": None,
        "chain_id_expected": None,
        "contract": None,
        "from_address": None,
        "pair_id": 0,
    }

    rpc = os.environ.get("OSTIUM_RPC_URL", "").strip()
    if not rpc:
        _fail("ostium.eg.env.rpc_url", "AUTH_MISSING_ENV",
              "OSTIUM_RPC_URL absent",
              next_action="Afegeix OSTIUM_RPC_URL=https://...")
    elif not re.match(r"^https?://", rpc):
        _fail("ostium.eg.env.rpc_url", "AUTH_INVALID_FORMAT",
              "OSTIUM_RPC_URL no és http(s)://...",
              next_action="OSTIUM_RPC_URL ha de ser https://...")
    else:
        preview = rpc[:50] + "..." if len(rpc) > 50 else rpc
        _pass("ostium.eg.env.rpc_url", f"OSTIUM_RPC_URL={preview!r}")
        out["rpc_url"] = rpc

    chain_str = os.environ.get("OSTIUM_CHAIN_ID", "").strip()
    if not chain_str:
        _info("ostium.eg.env.chain_id", "AUTH_MISSING_ENV",
              "OSTIUM_CHAIN_ID no configurat",
              next_action="Defineix OSTIUM_CHAIN_ID=421614 (testnet) o 42161 (mainnet)")
    else:
        try:
            out["chain_id_expected"] = int(chain_str)
            name = CHAIN_IDS.get(out["chain_id_expected"], "desconegut")
            _pass("ostium.eg.env.chain_id", f"OSTIUM_CHAIN_ID={out['chain_id_expected']} ({name})")
        except ValueError:
            _fail("ostium.eg.env.chain_id", "AUTH_INVALID_FORMAT",
                  f"OSTIUM_CHAIN_ID={chain_str!r} no és un enter",
                  next_action="OSTIUM_CHAIN_ID ha de ser un enter (ex: 421614)")

    contract = os.environ.get("OSTIUM_CONTRACT_ADDRESS", "").strip()
    if not contract:
        _fail("ostium.eg.env.contract", "AUTH_MISSING_ENV",
              "OSTIUM_CONTRACT_ADDRESS absent",
              next_action="Defineix OSTIUM_CONTRACT_ADDRESS=0x... (adreça del contract de trading)")
        out["contract"] = None
    elif not re.match(r"^0x[0-9a-fA-F]{40}$", contract):
        _fail("ostium.eg.env.contract", "AUTH_INVALID_FORMAT",
              f"OSTIUM_CONTRACT_ADDRESS format incorrecte: {contract!r}",
              next_action="L'adreça ha de ser 0x + 40 caràcters hex")
        out["contract"] = None
    else:
        _pass("ostium.eg.env.contract", f"OSTIUM_CONTRACT_ADDRESS={contract}")
        out["contract"] = contract

    from_addr = os.environ.get("OSTIUM_FROM_ADDRESS", "").strip()
    if not from_addr:
        _fail("ostium.eg.env.from_address", "AUTH_MISSING_ENV",
              "OSTIUM_FROM_ADDRESS absent",
              next_action="Defineix OSTIUM_FROM_ADDRESS=0x... (adreça que faria la TX)")
        out["from_address"] = None
    elif not re.match(r"^0x[0-9a-fA-F]{40}$", from_addr, re.IGNORECASE):
        _fail("ostium.eg.env.from_address", "AUTH_INVALID_FORMAT",
              "OSTIUM_FROM_ADDRESS format incorrecte",
              next_action="L'adreça ha de ser 0x + 40 caràcters hex")
        out["from_address"] = None
    else:
        _pass("ostium.eg.env.from_address", f"OSTIUM_FROM_ADDRESS={from_addr}")
        out["from_address"] = from_addr

    symbol = os.environ.get("OSTIUM_MARKET_SYMBOL", "EURUSD").strip().upper()
    pair_id = SYMBOL_TO_PAIR_ID.get(symbol)
    if pair_id is None:
        known = ", ".join(SYMBOL_TO_PAIR_ID.keys())
        _fail("ostium.eg.env.symbol", "AUTH_INVALID_FORMAT",
              f"OSTIUM_MARKET_SYMBOL={symbol!r} desconegut. Coneguts: {known}",
              next_action=f"Usa un symbol vàlid: {known}")
        out["pair_id"] = 0
    else:
        _pass("ostium.eg.env.symbol", f"OSTIUM_MARKET_SYMBOL={symbol} → pair_id={pair_id}")
        out["pair_id"] = pair_id

    return out


# ── Secció 2: Chain guard ─────────────────────────────────────────────────────


def check_chain(rpc_url: str, chain_id_expected: Optional[int]) -> bool:
    print("\n[2] Chain guard")
    result, err = _jsonrpc_simple(rpc_url, "eth_chainId", [])
    if err:
        _fail("ostium.eg.rpc.chain_id", err,
              f"RPC no respon a eth_chainId: {err}",
              next_action=_net_next(err))
        return False
    try:
        actual = int(result, 16) if isinstance(result, str) else int(result)
    except (ValueError, TypeError):
        _fail("ostium.eg.rpc.chain_id", "UNEXPECTED_PAYLOAD",
              f"eth_chainId valor inesperat: {result!r}",
              next_action="Comprova que OSTIUM_RPC_URL és un endpoint JSON-RPC vàlid")
        return False
    chain_name = CHAIN_IDS.get(actual, f"id={actual}")
    if chain_id_expected is not None and actual != chain_id_expected:
        exp_name = CHAIN_IDS.get(chain_id_expected, str(chain_id_expected))
        _fail("ostium.eg.rpc.chain_id", "CHAIN_MISMATCH",
              f"chain_id={actual} ({chain_name}) != OSTIUM_CHAIN_ID={chain_id_expected} ({exp_name})",
              next_action="Revisa OSTIUM_RPC_URL i OSTIUM_CHAIN_ID")
        return False
    _pass("ostium.eg.rpc.chain_id", f"chain_id={actual} ({chain_name})")
    return True


# ── Secció 3: eth_estimateGas ─────────────────────────────────────────────────


def check_estimate_gas(
    rpc_url: str,
    from_addr: str,
    to_addr: str,
    calldata_hex: str,
) -> None:
    print("\n[3] eth_estimateGas (0 TX)")
    print(f"    from={from_addr[:10]}... to={to_addr}")
    result_hex, err = _jsonrpc_estimate_gas(rpc_url, from_addr, to_addr, calldata_hex, "0x0")
    name = "ostium.eg.rpc.estimate_gas"
    if err is None and result_hex:
        try:
            gas_int = int(result_hex, 16)
            _pass(name, f"eth_estimateGas OK — gas={gas_int}")
        except (ValueError, TypeError):
            _pass(name, f"eth_estimateGas OK — result={result_hex}")
    elif err and err.startswith("CONTRACT_REVERT:"):
        revert_msg = err.removeprefix("CONTRACT_REVERT:")
        _fail(name, "CONTRACT_REVERT",
              f"eth_estimateGas revert: {revert_msg}",
              next_action="Revisa calldata, contract, symbol i chain (revert = simulació fallida)")
    else:
        cat = err or "UNEXPECTED_PAYLOAD"
        _fail(name, cat,
              f"Error eth_estimateGas: {cat}",
              next_action=_net_next(cat) if cat in ("DNS", "CONNECT_TIMEOUT", "CONNECT_REFUSED")
              else "Comprova OSTIUM_RPC_URL i contract")
    return None


# ── Report ────────────────────────────────────────────────────────────────────


def print_report() -> int:
    pass_n = sum(1 for r in results if r.status == "PASS")
    fail_n = sum(1 for r in results if r.status == "FAIL")
    info_n = sum(1 for r in results if r.status == "INFO")
    skip_n = sum(1 for r in results if r.status == "SKIP")
    print()
    print("─" * 60)
    print("  REPORT — smoke_ostium_preflight_estimate_gas")
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
    print(f"  Resultat: {pass_n} PASS, {fail_n} FAIL, {info_n} INFO, {skip_n} SKIP")
    if info_n:
        print(f"  INFO: no és FAIL — requereix atenció però no bloqueja")
    print("─" * 60)
    return 0 if fail_n == 0 else 1


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    print("── smoke_ostium_preflight_estimate_gas.py ─────────────────────")
    print("   eth_estimateGas only (0 signing, 0 send)")
    print(f"   SMOKE_TIMEOUT = {TIMEOUT}s")

    cfg = check_env()
    rpc_url = cfg["rpc_url"]
    if rpc_url is None:
        _skip("ostium.eg.rpc.chain_id", "SKIP — OSTIUM_RPC_URL absent")
        _skip("ostium.eg.rpc.estimate_gas", "SKIP — OSTIUM_RPC_URL absent")
        return print_report()

    if cfg["contract"] is None or cfg["from_address"] is None:
        _skip("ostium.eg.rpc.chain_id", "SKIP — contract o from_address invàlid")
        _skip("ostium.eg.rpc.estimate_gas", "SKIP — contract o from_address invàlid")
        return print_report()

    chain_ok = check_chain(rpc_url, cfg["chain_id_expected"])
    if not chain_ok:
        _skip("ostium.eg.rpc.estimate_gas", "SKIP — chain mismatch o RPC inaccessible")
        return print_report()

    calldata = build_get_open_trade_calldata(
        cfg["from_address"],
        cfg["pair_id"],
        0,
    )
    calldata_hex = "0x" + calldata.hex()
    check_estimate_gas(
        rpc_url=rpc_url,
        from_addr=cfg["from_address"],
        to_addr=cfg["contract"],
        calldata_hex=calldata_hex,
    )
    return print_report()


if __name__ == "__main__":
    sys.exit(main())
