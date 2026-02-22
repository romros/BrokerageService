#!/usr/bin/env python3
"""
smoke_ostium_readonly.py — Ostium read-only smoke (opt-in, 0 transaccions).

Comprova:
  1. ENV vars Ostium (sense mostrar secrets)
  2. RPC liveness + block height (eth_chainId, eth_blockNumber)
  3. Chain ID vs OSTIUM_CHAIN_ID (FAIL si mismatch)
  4. Subgraph probe (INFO/SKIP per defecte; FAIL si --require-subgraph)

Categories d'error (alineades amb Ops-1a):
  AUTH_MISSING_ENV    — variable obligatòria absent o buida
  AUTH_INVALID_FORMAT — format incorrecte (0x hex)
  DNS                 — hostname no resolvible
  CONNECT_TIMEOUT     — timeout de connexió
  CONNECT_REFUSED     — connexió refusada
  HTTP_4XX / HTTP_5XX — resposta HTTP
  CHAIN_MISMATCH      — chain_id retornat != OSTIUM_CHAIN_ID
  SUBGRAPH_STALE      — subgraph respon però sembla no indexar (INFO)
  UNEXPECTED_PAYLOAD  — resposta inesperada

Ús:
  python3 scripts/network_smokes/smoke_ostium_readonly.py
  python3 scripts/network_smokes/smoke_ostium_readonly.py --require-subgraph

Variables d'entorn:
  OSTIUM_RPC_URL         (obligatori)
  OSTIUM_CHAIN_ID        (recomanat; absent → INFO)
  OSTIUM_SUBGRAPH_URL    (opcional; absent → SKIP subgraph probe)
  OSTIUM_PRIVATE_KEY     (opcional; si present → valida format, NO mostra valor)
  OSTIUM_WALLET_ADDRESS  (opcional; si present → valida format)
  SMOKE_TIMEOUT          (default: 5s)

Refs:
  lab/ostium/RESULTS.md — subgraph testnet known-broken; workaround via brute-force trade_index
  lab/ostium/scripts/test_subgraph_quick.py — query GraphQL de referència

IMPORTANT: Read-only absolut. Cap TX. No secrets en logs.
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


# ── Configuració ──────────────────────────────────────────────────────────────

TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "5"))
REQUIRE_SUBGRAPH = "--require-subgraph" in sys.argv

# Chain IDs coneguts
CHAIN_IDS = {
    42161: "Arbitrum One (mainnet)",
    421614: "Arbitrum Sepolia (testnet)",
}

# Subgraph query mínima (mateixa semàntica que lab/ostium/scripts/test_subgraph_quick.py)
_SUBGRAPH_QUERY = """
{
  openTrades(first: 1) {
    id
    pairId
    index
  }
}
"""


# ── Model de resultat ─────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str    # "PASS" | "FAIL" | "INFO" | "SKIP"
    category: str  # "OK", "AUTH_MISSING_ENV", "CHAIN_MISMATCH", ...
    detail: str
    next_action: str = ""


results: list[CheckResult] = []


# ── Helpers ───────────────────────────────────────────────────────────────────


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
    """INFO: no és FAIL, però cal atenció. No incrementa exit code."""
    r = CheckResult(name=name, status="INFO", category=category,
                    detail=detail, next_action=next_action)
    results.append(r)
    return r


def _skip(name: str, detail: str = "") -> CheckResult:
    r = CheckResult(name=name, status="SKIP", category="OK", detail=detail)
    results.append(r)
    return r


def _net_error_category(reason: str) -> str:
    r = reason.lower()
    if "timed out" in r or "timeout" in r:
        return "CONNECT_TIMEOUT"
    if "connection refused" in r:
        return "CONNECT_REFUSED"
    return "CONNECT_TIMEOUT"


def _next_action_net(cat: str) -> str:
    if cat == "DNS":
        return "Comprova DNS, proxy, VPN o si el host és accessible"
    if cat == "CONNECT_TIMEOUT":
        return f"Timeout ({TIMEOUT}s) — comprova que el RPC sigui accessible"
    if cat == "CONNECT_REFUSED":
        return "Connexió refusada — comprova la URL del RPC"
    return "Comprova connectivitat de xarxa"


# ── JSON-RPC helper (sense requests, només urllib) ────────────────────────────


def _jsonrpc(url: str, method: str, params: list) -> tuple[Optional[object], Optional[str]]:
    """
    Fa una crida JSON-RPC 2.0 via POST.
    Retorna (result, error_category).
    result és el camp "result" de la resposta, o None si error.
    error_category és string de categoria si error de xarxa, None si OK.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    try:
        socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, "DNS"

    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BrokerageService-NetworkSmoke/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            data = json.loads(body)
            if "error" in data:
                return None, "UNEXPECTED_PAYLOAD"
            return data.get("result"), None
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            return None, "HTTP_4XX"
        return None, "HTTP_5XX"
    except urllib.error.URLError as e:
        return None, _net_error_category(str(e.reason))
    except TimeoutError:
        return None, "CONNECT_TIMEOUT"
    except (json.JSONDecodeError, KeyError):
        return None, "UNEXPECTED_PAYLOAD"


# ── GraphQL helper (sense requests, només urllib) ─────────────────────────────


def _graphql_post(url: str, query: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Fa una POST GraphQL mínima.
    Retorna (data_dict, error_category).
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    try:
        socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, "DNS"

    payload = json.dumps({"query": query}).encode("utf-8")

    try:
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BrokerageService-NetworkSmoke/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            data = json.loads(body)
            return data, None
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            return None, "HTTP_4XX"
        return None, "HTTP_5XX"
    except urllib.error.URLError as e:
        return None, _net_error_category(str(e.reason))
    except TimeoutError:
        return None, "CONNECT_TIMEOUT"
    except (json.JSONDecodeError, KeyError):
        return None, "UNEXPECTED_PAYLOAD"


# ── Secció 1: ENV vars ────────────────────────────────────────────────────────


def check_env() -> Optional[str]:
    """
    Valida les ENV vars Ostium.
    Retorna OSTIUM_RPC_URL si present, None si absent (FAIL).
    """
    print("\n[1] ENV vars Ostium")

    rpc_url = os.environ.get("OSTIUM_RPC_URL", "").strip()
    if not rpc_url:
        _fail("ostium.env.rpc_url", "AUTH_MISSING_ENV",
              "OSTIUM_RPC_URL absent o buida",
              next_action="Afegeix OSTIUM_RPC_URL=https://arb-sepolia.g.alchemy.com/v2/KEY a l'entorn")
        rpc_url = None
    else:
        if re.match(r"^https?://", rpc_url):
            _pass("ostium.env.rpc_url", f"OSTIUM_RPC_URL present ({rpc_url[:40]}...)" if len(rpc_url) > 40 else f"OSTIUM_RPC_URL={rpc_url!r}")
        else:
            _fail("ostium.env.rpc_url", "AUTH_INVALID_FORMAT",
                  "OSTIUM_RPC_URL no és http(s)://...",
                  next_action="OSTIUM_RPC_URL ha de ser https://...")
            rpc_url = None

    # OSTIUM_CHAIN_ID (recomanat, no obligatori)
    chain_id_str = os.environ.get("OSTIUM_CHAIN_ID", "").strip()
    if not chain_id_str:
        _info("ostium.env.chain_id", "AUTH_MISSING_ENV",
              "OSTIUM_CHAIN_ID no configurat",
              next_action="Defineix OSTIUM_CHAIN_ID=421614 (testnet) o 42161 (mainnet) per validar chain mismatch")
    else:
        try:
            chain_id = int(chain_id_str)
            name = CHAIN_IDS.get(chain_id, "desconegut")
            _pass("ostium.env.chain_id", f"OSTIUM_CHAIN_ID={chain_id} ({name})")
        except ValueError:
            _fail("ostium.env.chain_id", "AUTH_INVALID_FORMAT",
                  f"OSTIUM_CHAIN_ID={chain_id_str!r} no és un enter",
                  next_action="OSTIUM_CHAIN_ID ha de ser un enter (ex: 421614)")

    # OSTIUM_SUBGRAPH_URL (opcional)
    sg_url = os.environ.get("OSTIUM_SUBGRAPH_URL", "").strip()
    if sg_url:
        _pass("ostium.env.subgraph_url", f"OSTIUM_SUBGRAPH_URL present ({sg_url[:50]}...)" if len(sg_url) > 50 else f"OSTIUM_SUBGRAPH_URL={sg_url!r}")
    else:
        _skip("ostium.env.subgraph_url", "OSTIUM_SUBGRAPH_URL no configurat (SKIP subgraph probe)")

    # OSTIUM_PRIVATE_KEY (opcional — mai mostrat)
    pk = os.environ.get("OSTIUM_PRIVATE_KEY", "").strip()
    if pk:
        if re.match(r"^0x[0-9a-fA-F]{64}$", pk):
            _pass("ostium.env.private_key", "OSTIUM_PRIVATE_KEY present, format 0x[64hex] OK (valor ocult)")
        else:
            _fail("ostium.env.private_key", "AUTH_INVALID_FORMAT",
                  "OSTIUM_PRIVATE_KEY present però format incorrecte (no és 0x[64hex])",
                  next_action="La clau ha de tenir el format 0x + 64 caràcters hex")
    else:
        _skip("ostium.env.private_key", "OSTIUM_PRIVATE_KEY no configurat (opcional)")

    # OSTIUM_WALLET_ADDRESS (opcional)
    wallet = os.environ.get("OSTIUM_WALLET_ADDRESS", "").strip()
    if wallet:
        if re.match(r"^0x[0-9a-fA-F]{40}$", wallet, re.IGNORECASE):
            _pass("ostium.env.wallet_address", f"OSTIUM_WALLET_ADDRESS={wallet} format OK")
        else:
            _fail("ostium.env.wallet_address", "AUTH_INVALID_FORMAT",
                  f"OSTIUM_WALLET_ADDRESS format incorrecte: {wallet!r}",
                  next_action="L'adreça ha de tenir el format 0x + 40 caràcters hex")
    else:
        _skip("ostium.env.wallet_address", "OSTIUM_WALLET_ADDRESS no configurat (opcional)")

    return rpc_url


# ── Secció 2: RPC liveness + chain guard ─────────────────────────────────────


def check_rpc(rpc_url: str) -> None:
    print(f"\n[2] RPC liveness + chain")
    print(f"    OSTIUM_RPC_URL = {rpc_url[:60]}{'...' if len(rpc_url) > 60 else ''}")

    # 2a. eth_blockNumber — liveness
    result, err = _jsonrpc(rpc_url, "eth_blockNumber", [])
    if err:
        _fail("ostium.rpc.liveness", err,
              f"RPC no respon a eth_blockNumber: {err}",
              next_action=_next_action_net(err))
        # Si no respon, no té sentit continuar amb chain_id
        _skip("ostium.rpc.chain_id", "SKIP — RPC no accessible")
        return

    try:
        block_number = int(result, 16) if isinstance(result, str) else int(result)
        _pass("ostium.rpc.liveness", f"eth_blockNumber → block={block_number:,}")
    except (ValueError, TypeError):
        _fail("ostium.rpc.liveness", "UNEXPECTED_PAYLOAD",
              f"eth_blockNumber retorna valor inesperat: {result!r}",
              next_action="Comprova que OSTIUM_RPC_URL és un endpoint JSON-RPC Ethereum vàlid")
        _skip("ostium.rpc.chain_id", "SKIP — liveness fallat")
        return

    # 2b. eth_chainId — chain guard
    result_chain, err_chain = _jsonrpc(rpc_url, "eth_chainId", [])
    if err_chain:
        _fail("ostium.rpc.chain_id", err_chain,
              f"RPC no respon a eth_chainId: {err_chain}",
              next_action=_next_action_net(err_chain))
        return

    try:
        actual_chain_id = int(result_chain, 16) if isinstance(result_chain, str) else int(result_chain)
    except (ValueError, TypeError):
        _fail("ostium.rpc.chain_id", "UNEXPECTED_PAYLOAD",
              f"eth_chainId retorna valor inesperat: {result_chain!r}",
              next_action="Comprova que OSTIUM_RPC_URL és un endpoint JSON-RPC Ethereum vàlid")
        return

    chain_name = CHAIN_IDS.get(actual_chain_id, f"desconegut ({actual_chain_id})")

    # Comparar si OSTIUM_CHAIN_ID definit
    expected_str = os.environ.get("OSTIUM_CHAIN_ID", "").strip()
    if expected_str:
        try:
            expected_chain_id = int(expected_str)
            if actual_chain_id == expected_chain_id:
                _pass("ostium.rpc.chain_id",
                      f"chain_id={actual_chain_id} ({chain_name}) — coincideix amb OSTIUM_CHAIN_ID")
            else:
                expected_name = CHAIN_IDS.get(expected_chain_id, str(expected_chain_id))
                _fail("ostium.rpc.chain_id", "CHAIN_MISMATCH",
                      f"chain_id={actual_chain_id} ({chain_name}) != OSTIUM_CHAIN_ID={expected_chain_id} ({expected_name})",
                      next_action="Revisa OSTIUM_RPC_URL i OSTIUM_CHAIN_ID — probablement apuntes a una xarxa incorrecta")
        except ValueError:
            _info("ostium.rpc.chain_id", "AUTH_INVALID_FORMAT",
                  f"OSTIUM_CHAIN_ID={expected_str!r} no parsejable — chain real={actual_chain_id} ({chain_name})",
                  next_action="Corregeix OSTIUM_CHAIN_ID per poder validar chain mismatch")
    else:
        _info("ostium.rpc.chain_id", "AUTH_MISSING_ENV",
              f"OSTIUM_CHAIN_ID no definit — chain real={actual_chain_id} ({chain_name})",
              next_action=f"Afegeix OSTIUM_CHAIN_ID={actual_chain_id} per validar chain mismatch en futures execucions")


# ── Secció 3: Subgraph probe ──────────────────────────────────────────────────


def check_subgraph() -> None:
    sg_url = os.environ.get("OSTIUM_SUBGRAPH_URL", "").strip()

    if not sg_url:
        # Intent de probe amb URL per defecte (testnet) si no configurat?
        # No: seguim política "SKIP si no configurat" (no hardcodegem URLs de producció)
        print("\n[3] Subgraph probe — SKIP (OSTIUM_SUBGRAPH_URL no configurat)")
        return

    mode = "FAIL si error (--require-subgraph)" if REQUIRE_SUBGRAPH else "INFO si error (default)"
    print(f"\n[3] Subgraph probe")
    print(f"    OSTIUM_SUBGRAPH_URL = {sg_url[:60]}{'...' if len(sg_url) > 60 else ''}")
    print(f"    Mode: {mode}")

    data, err = _graphql_post(sg_url, _SUBGRAPH_QUERY)

    name = "ostium.subgraph"

    if err:
        detail = f"Error de xarxa al subgraph: {err}"
        nxt = _next_action_net(err) if err in ("DNS", "CONNECT_TIMEOUT", "CONNECT_REFUSED") else \
              "Comprova OSTIUM_SUBGRAPH_URL i accessibilitat"
        if REQUIRE_SUBGRAPH:
            _fail(name, err, detail, next_action=nxt)
        else:
            _info(name, err, detail + " (INFO — pot ser known-broken a testnet)", next_action=nxt)
        return

    # Comprova errors GraphQL
    if "errors" in data:
        errs = data["errors"]
        detail = f"GraphQL errors: {errs[:1]}"
        nxt = "Comprova que la URL del subgraph és correcta i el schema és l'esperat"
        if REQUIRE_SUBGRAPH:
            _fail(name, "UNEXPECTED_PAYLOAD", detail, next_action=nxt)
        else:
            _info(name, "UNEXPECTED_PAYLOAD", detail, next_action=nxt)
        return

    # Comprova que la resposta té 'data'
    if "data" not in data:
        detail = f"Resposta sense camp 'data': {str(data)[:80]}"
        if REQUIRE_SUBGRAPH:
            _fail(name, "UNEXPECTED_PAYLOAD", detail,
                  next_action="El subgraph no retorna 'data' — pot estar down o esquema canviat")
        else:
            _info(name, "UNEXPECTED_PAYLOAD", detail,
                  next_action="El subgraph no retorna 'data' — known-broken a testnet (workaround: no_subgraph)")
        return

    open_trades = data["data"].get("openTrades", None)

    if open_trades is None:
        # El camp no existeix — subgraph no indexa o schema diferent
        detail = "openTrades absent de la resposta — subgraph probablement no indexant"
        if REQUIRE_SUBGRAPH:
            _fail(name, "SUBGRAPH_STALE", detail,
                  next_action="Subgraph no indexa. Comprova l'estat de l'índex a The Graph Studio")
        else:
            _info(name, "SUBGRAPH_STALE", detail,
                  next_action="Known-broken a testnet: no dependre del subgraph; usa workaround LAB test_full_cycle_no_subgraph")
        return

    # Respon OK (pot ser llista buida si no hi ha trades oberts)
    n_trades = len(open_trades)
    _pass(name, f"subgraph respon OK — openTrades={n_trades} (pot ser 0 si no hi ha trades oberts)")


# ── Report ────────────────────────────────────────────────────────────────────


def print_report() -> int:
    pass_n  = sum(1 for r in results if r.status == "PASS")
    fail_n  = sum(1 for r in results if r.status == "FAIL")
    info_n  = sum(1 for r in results if r.status == "INFO")
    skip_n  = sum(1 for r in results if r.status == "SKIP")

    print()
    print("─" * 60)
    print("  REPORT — smoke_ostium_readonly")
    if REQUIRE_SUBGRAPH:
        print("  Mode: --require-subgraph (subgraph FAIL → exit 1)")
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
    print("── smoke_ostium_readonly.py ───────────────────────────")
    if REQUIRE_SUBGRAPH:
        print("   Mode: --require-subgraph actiu")

    rpc_url = check_env()

    if rpc_url:
        check_rpc(rpc_url)
    else:
        _skip("ostium.rpc.liveness", "SKIP — OSTIUM_RPC_URL absent")
        _skip("ostium.rpc.chain_id", "SKIP — OSTIUM_RPC_URL absent")

    check_subgraph()

    return print_report()


if __name__ == "__main__":
    sys.exit(main())
