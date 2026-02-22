#!/usr/bin/env python3
"""
smoke_ostium_preflight_call.py — Ostium eth_call preflight (0 TX, opt-in).

Valida el stack complet d'Ostium fins al contract, sense enviar cap TX:
  1. ENV vars (amb validació de format, sense mostrar secrets)
  2. Chain guard (eth_chainId vs OSTIUM_CHAIN_ID)
  3. eth_call → getOpenTrade(wallet, pair_id=0, index=0)
     - Funció "view" del contract de trading → SEMPRE 0 TX
     - PASS si retorna dades (trade pot ser buit/zeros = OK)
     - FAIL CONTRACT_REVERT si el contract reverteix (adreça errònia, chain errònia, etc.)

Refs:
  infrastructure/venues/ostium/ostium_client.py — TRADING_CONTRACT_*, GET_OPEN_TRADE_ABI
  lab/ostium/scripts/test_full_cycle_no_subgraph.py — flux real validat

ABI de getOpenTrade (del codi de producció):
  inputs:  (address trader, uint16 pairId, uint8 index)
  outputs: (uint192 openPrice, uint192 tp, uint192 sl,
            uint192 collateral, uint32 leverage, bool isLong)
  stateMutability: view

Encoding ABI manual (stdlib):
  selector = keccak256("getOpenTrade(address,uint16,uint8)")[:4]
  data = selector + pad32(address) + pad32(uint16) + pad32(uint8)

Categories d'error:
  AUTH_MISSING_ENV     — variable obligatòria absent
  AUTH_INVALID_FORMAT  — format incorrecte
  DNS / CONNECT_TIMEOUT / CONNECT_REFUSED — xarxa
  CHAIN_MISMATCH       — chain_id != OSTIUM_CHAIN_ID
  CONTRACT_REVERT      — eth_call revertida (adreça, chain, params)
  UNEXPECTED_PAYLOAD   — resposta inesperada del RPC

Variables d'entorn:
  OSTIUM_RPC_URL           (obligatori)
  OSTIUM_CHAIN_ID          (recomanat: 421614=testnet, 42161=mainnet)
  OSTIUM_CONTRACT_ADDRESS  (obligatori; default: 0x2A9B9... testnet)
  OSTIUM_WALLET_ADDRESS    (recomanat; si absent usa 0x0...0 dummy)
  OSTIUM_MARKET_SYMBOL     (opcional; default EURUSD → pair_id=0)
  SMOKE_TIMEOUT            (default: 5s)

Ús:
  python3 scripts/network_smokes/smoke_ostium_preflight_call.py
"""

import hashlib
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


# ── Constants (font: infrastructure/venues/ostium/ostium_client.py) ───────────

TRADING_CONTRACT_TESTNET = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"
TRADING_CONTRACT_MAINNET = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"  # TODO: verificar mainnet

SYMBOL_TO_PAIR_ID = {
    "EURUSD": 0, "XAUUSD": 1, "BTCUSD": 2, "ETHUSD": 3,
    "GBPUSD": 4, "GBPJPY": 5, "USDJPY": 6, "USDCHF": 7,
    "AUDUSD": 8, "USDCAD": 9,
}

CHAIN_IDS = {
    42161: "Arbitrum One (mainnet)",
    421614: "Arbitrum Sepolia (testnet)",
}

# ── Configuració ──────────────────────────────────────────────────────────────

TIMEOUT = int(os.environ.get("SMOKE_TIMEOUT", "5"))


# ── Model de resultat ─────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str    # "PASS" | "FAIL" | "INFO" | "SKIP"
    category: str
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


# ── ABI encoding manual (keccak4 + ABI pad32) ────────────────────────────────


def _keccak256(data: bytes) -> bytes:
    """Keccak-256 via hashlib (Python 3.6+)."""
    return hashlib.new("sha3_256", data).digest()


def _function_selector(signature: str) -> bytes:
    """Retorna els primers 4 bytes del keccak256 de la signatura de la funció."""
    return _keccak256(signature.encode("ascii"))[:4]


def _encode_address(addr: str) -> bytes:
    """Codifica una adreça Ethereum com a 32 bytes (24 zeros + 20 bytes)."""
    addr_clean = addr.lower().removeprefix("0x")
    addr_bytes = bytes.fromhex(addr_clean.zfill(40))
    return b"\x00" * 12 + addr_bytes  # 32 bytes total


def _encode_uint(value: int) -> bytes:
    """Codifica un uint com a 32 bytes big-endian."""
    return value.to_bytes(32, "big")


def build_get_open_trade_calldata(trader: str, pair_id: int, index: int) -> bytes:
    """
    Construeix el calldata per a getOpenTrade(address, uint16, uint8).

    Encoding ABI:
      selector (4 bytes) + address (32 bytes) + uint16 (32 bytes) + uint8 (32 bytes)
    """
    selector = _function_selector("getOpenTrade(address,uint16,uint8)")
    return selector + _encode_address(trader) + _encode_uint(pair_id) + _encode_uint(index)


# ── JSON-RPC eth_call ─────────────────────────────────────────────────────────


def _jsonrpc_eth_call(
    rpc_url: str,
    to: str,
    data_hex: str,
    block: str = "latest",
) -> tuple[Optional[str], Optional[str]]:
    """
    Fa una crida JSON-RPC eth_call.
    Retorna (result_hex, error_category).
    result_hex és la resposta (0x...) si OK, None si error.
    error_category: None si ok, string categoria si error.
    """
    parsed = urlparse(rpc_url)
    host = parsed.hostname or ""

    try:
        socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, "DNS"

    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": to, "data": data_hex}, block],
        "id": 1,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            rpc_url, data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BrokerageService-NetworkSmoke/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            data = json.loads(body)

            # Revert explícit: {"jsonrpc":"2.0","error":{"code":-32000,"message":"..."},"id":1}
            if "error" in data:
                err = data["error"]
                code = err.get("code", 0)
                msg = err.get("message", "")
                # -32000 = execution reverted; -32015 = VM execution error
                if code in (-32000, -32015) or "revert" in msg.lower() or "execution" in msg.lower():
                    return None, f"CONTRACT_REVERT:{msg[:120]}"
                return None, f"UNEXPECTED_PAYLOAD:{msg[:80]}"

            result = data.get("result", "")
            return result, None

    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            return None, "HTTP_4XX"
        return None, "HTTP_5XX"
    except urllib.error.URLError as e:
        return None, _net_category(str(e.reason))
    except TimeoutError:
        return None, "CONNECT_TIMEOUT"
    except (json.JSONDecodeError, KeyError):
        return None, "UNEXPECTED_PAYLOAD"


def _jsonrpc_simple(rpc_url: str, method: str, params: list) -> tuple[Optional[object], Optional[str]]:
    """Crida JSON-RPC genèrica (eth_chainId, eth_blockNumber, etc.)."""
    parsed = urlparse(rpc_url)
    host = parsed.hostname or ""
    try:
        socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return None, "DNS"
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    try:
        req = urllib.request.Request(rpc_url, data=payload, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "BrokerageService-NetworkSmoke/1.0"})
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


# ── Secció 1: ENV vars ────────────────────────────────────────────────────────


def check_env() -> dict:
    """
    Valida les ENV vars. Retorna dict amb valors resolts (rpc_url, contract, wallet, pair_id).
    Valors None si la validació falla per a aquell camp.
    """
    print("\n[1] ENV vars Ostium preflight")

    out: dict = {
        "rpc_url": None,
        "chain_id_expected": None,
        "contract": None,
        "wallet": None,
        "pair_id": 0,
    }

    # OSTIUM_RPC_URL (obligatori)
    rpc = os.environ.get("OSTIUM_RPC_URL", "").strip()
    if not rpc:
        _fail("ostium.pf.env.rpc_url", "AUTH_MISSING_ENV",
              "OSTIUM_RPC_URL absent",
              next_action="Afegeix OSTIUM_RPC_URL=https://arb-sepolia.g.alchemy.com/v2/KEY")
    elif not re.match(r"^https?://", rpc):
        _fail("ostium.pf.env.rpc_url", "AUTH_INVALID_FORMAT",
              "OSTIUM_RPC_URL no és http(s)://...",
              next_action="OSTIUM_RPC_URL ha de ser https://...")
    else:
        preview = rpc[:50] + "..." if len(rpc) > 50 else rpc
        _pass("ostium.pf.env.rpc_url", f"OSTIUM_RPC_URL={preview!r}")
        out["rpc_url"] = rpc

    # OSTIUM_CHAIN_ID (recomanat)
    chain_str = os.environ.get("OSTIUM_CHAIN_ID", "").strip()
    if not chain_str:
        _info("ostium.pf.env.chain_id", "AUTH_MISSING_ENV",
              "OSTIUM_CHAIN_ID no configurat",
              next_action="Defineix OSTIUM_CHAIN_ID=421614 (testnet) o 42161 (mainnet)")
    else:
        try:
            out["chain_id_expected"] = int(chain_str)
            name = CHAIN_IDS.get(out["chain_id_expected"], "desconegut")
            _pass("ostium.pf.env.chain_id", f"OSTIUM_CHAIN_ID={out['chain_id_expected']} ({name})")
        except ValueError:
            _fail("ostium.pf.env.chain_id", "AUTH_INVALID_FORMAT",
                  f"OSTIUM_CHAIN_ID={chain_str!r} no és un enter",
                  next_action="OSTIUM_CHAIN_ID ha de ser un enter (ex: 421614)")

    # OSTIUM_CONTRACT_ADDRESS (obligatori; fallback testnet)
    contract = os.environ.get("OSTIUM_CONTRACT_ADDRESS", "").strip()
    if not contract:
        contract = TRADING_CONTRACT_TESTNET
        _info("ostium.pf.env.contract", "AUTH_MISSING_ENV",
              f"OSTIUM_CONTRACT_ADDRESS absent — usant default testnet: {contract}",
              next_action="Defineix OSTIUM_CONTRACT_ADDRESS per usar una adreça específica")
    elif not re.match(r"^0x[0-9a-fA-F]{40}$", contract):
        _fail("ostium.pf.env.contract", "AUTH_INVALID_FORMAT",
              f"OSTIUM_CONTRACT_ADDRESS format incorrecte: {contract!r}",
              next_action="L'adreça ha de ser 0x + 40 caràcters hex")
        contract = None
    else:
        _pass("ostium.pf.env.contract", f"OSTIUM_CONTRACT_ADDRESS={contract}")
    out["contract"] = contract

    # OSTIUM_WALLET_ADDRESS (recomanat; fallback 0x0)
    wallet = os.environ.get("OSTIUM_WALLET_ADDRESS", "").strip()
    ZERO_ADDR = "0x" + "0" * 40
    if not wallet:
        wallet = ZERO_ADDR
        _info("ostium.pf.env.wallet", "AUTH_MISSING_ENV",
              f"OSTIUM_WALLET_ADDRESS absent — usant 0x0 dummy (getOpenTrade retornarà zeros)",
              next_action="Defineix OSTIUM_WALLET_ADDRESS per veure trades reals de la wallet")
    elif not re.match(r"^0x[0-9a-fA-F]{40}$", wallet, re.IGNORECASE):
        _fail("ostium.pf.env.wallet", "AUTH_INVALID_FORMAT",
              "OSTIUM_WALLET_ADDRESS format incorrecte",
              next_action="L'adreça ha de ser 0x + 40 caràcters hex")
        wallet = ZERO_ADDR
    else:
        _pass("ostium.pf.env.wallet", f"OSTIUM_WALLET_ADDRESS={wallet}")
    out["wallet"] = wallet

    # OSTIUM_MARKET_SYMBOL (opcional; default EURUSD → pair_id=0)
    symbol = os.environ.get("OSTIUM_MARKET_SYMBOL", "EURUSD").strip().upper()
    pair_id = SYMBOL_TO_PAIR_ID.get(symbol)
    if pair_id is None:
        known = ", ".join(SYMBOL_TO_PAIR_ID.keys())
        _fail("ostium.pf.env.symbol", "AUTH_INVALID_FORMAT",
              f"OSTIUM_MARKET_SYMBOL={symbol!r} desconegut. Coneguts: {known}",
              next_action=f"Usa un symbol vàlid: {known}")
        out["pair_id"] = 0  # fallback
    else:
        _pass("ostium.pf.env.symbol", f"OSTIUM_MARKET_SYMBOL={symbol} → pair_id={pair_id}")
        out["pair_id"] = pair_id

    return out


# ── Secció 2: Chain guard ─────────────────────────────────────────────────────


def check_chain(rpc_url: str, chain_id_expected: Optional[int]) -> bool:
    """Valida chain_id. Retorna True si ok per continuar, False si mismatch crític."""
    print(f"\n[2] Chain guard")

    result, err = _jsonrpc_simple(rpc_url, "eth_chainId", [])
    if err:
        _fail("ostium.pf.chain_id", err,
              f"RPC no respon a eth_chainId: {err}",
              next_action=_net_next(err))
        return False

    try:
        actual = int(result, 16) if isinstance(result, str) else int(result)
    except (ValueError, TypeError):
        _fail("ostium.pf.chain_id", "UNEXPECTED_PAYLOAD",
              f"eth_chainId retorna valor inesperat: {result!r}",
              next_action="Comprova que OSTIUM_RPC_URL és un endpoint JSON-RPC Ethereum vàlid")
        return False

    chain_name = CHAIN_IDS.get(actual, f"id={actual}")

    if chain_id_expected is not None and actual != chain_id_expected:
        exp_name = CHAIN_IDS.get(chain_id_expected, str(chain_id_expected))
        _fail("ostium.pf.chain_id", "CHAIN_MISMATCH",
              f"chain_id={actual} ({chain_name}) != OSTIUM_CHAIN_ID={chain_id_expected} ({exp_name})",
              next_action="Revisa OSTIUM_RPC_URL i OSTIUM_CHAIN_ID — probablement apuntes a una xarxa incorrecta")
        return False

    _pass("ostium.pf.chain_id",
          f"chain_id={actual} ({chain_name})")
    return True


# ── Secció 3: eth_call → getOpenTrade ────────────────────────────────────────


def check_preflight_call(rpc_url: str, contract: str, wallet: str, pair_id: int) -> None:
    """
    Fa eth_call a getOpenTrade(wallet, pair_id, 0) — funció view, 0 TX.

    PASS: el contract respon (trade pot ser buit/zeros = vàlid)
    FAIL CONTRACT_REVERT: el contract reverteix (adreça errònia, chain errònia, etc.)
    """
    print(f"\n[3] eth_call → getOpenTrade({wallet[:10]}..., pair_id={pair_id}, index=0)")
    print(f"    Contract: {contract}")

    calldata = build_get_open_trade_calldata(wallet, pair_id, 0)
    data_hex = "0x" + calldata.hex()

    result_hex, err = _jsonrpc_eth_call(rpc_url, contract, data_hex)

    name = "ostium.pf.call.getOpenTrade"

    if err is None:
        # Resposta vàlida — decodifiquem per mostrar info útil (best-effort)
        detail = f"eth_call OK"
        if result_hex and len(result_hex) > 2:
            raw = bytes.fromhex(result_hex.removeprefix("0x"))
            # 6 camps: uint192×4, uint32, bool → 6 × 32 bytes = 192 bytes esperats
            if len(raw) >= 192:
                collateral_raw = int.from_bytes(raw[96:128], "big")
                is_long_raw = int.from_bytes(raw[160:192], "big")
                if collateral_raw > 0:
                    collateral = collateral_raw / 1e18
                    side = "LONG" if is_long_raw else "SHORT"
                    detail += f" — trade actiu: collateral={collateral:.4f} USDC ({side})"
                else:
                    detail += f" — trade index 0 buit (collateral=0, normal si no hi ha trade obert)"
            else:
                detail += f" — resposta {len(raw)} bytes (payload curt)"
        _pass(name, detail)

    elif err and err.startswith("CONTRACT_REVERT:"):
        revert_msg = err.removeprefix("CONTRACT_REVERT:")
        _fail(name, "CONTRACT_REVERT",
              f"eth_call revertida: {revert_msg}",
              next_action=(
                  "Possible causa: OSTIUM_CONTRACT_ADDRESS incorrecta, chain errònia, "
                  "o adreça de wallet malformada. Comprova OSTIUM_CONTRACT_ADDRESS i OSTIUM_CHAIN_ID"
              ))
    else:
        cat = err or "UNEXPECTED_PAYLOAD"
        _fail(name, cat,
              f"Error a eth_call: {cat}",
              next_action=_net_next(cat) if cat in ("DNS", "CONNECT_TIMEOUT", "CONNECT_REFUSED")
              else "Comprova OSTIUM_RPC_URL i que el contract sigui accessible")


# ── Report ────────────────────────────────────────────────────────────────────


def print_report() -> int:
    pass_n = sum(1 for r in results if r.status == "PASS")
    fail_n = sum(1 for r in results if r.status == "FAIL")
    info_n = sum(1 for r in results if r.status == "INFO")
    skip_n = sum(1 for r in results if r.status == "SKIP")

    print()
    print("─" * 60)
    print("  REPORT — smoke_ostium_preflight_call")
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
    print("── smoke_ostium_preflight_call.py ─────────────────────")
    print("   eth_call → getOpenTrade (view, 0 TX)")
    print(f"   SMOKE_TIMEOUT = {TIMEOUT}s")

    cfg = check_env()

    rpc_url = cfg["rpc_url"]
    if rpc_url is None:
        _skip("ostium.pf.chain_id", "SKIP — OSTIUM_RPC_URL absent")
        _skip("ostium.pf.call.getOpenTrade", "SKIP — OSTIUM_RPC_URL absent")
        return print_report()

    if cfg["contract"] is None:
        _skip("ostium.pf.chain_id", "SKIP — OSTIUM_CONTRACT_ADDRESS invàlid")
        _skip("ostium.pf.call.getOpenTrade", "SKIP — OSTIUM_CONTRACT_ADDRESS invàlid")
        return print_report()

    chain_ok = check_chain(rpc_url, cfg["chain_id_expected"])
    if not chain_ok:
        _skip("ostium.pf.call.getOpenTrade", "SKIP — chain mismatch o RPC inaccessible")
        return print_report()

    check_preflight_call(
        rpc_url=rpc_url,
        contract=cfg["contract"],
        wallet=cfg["wallet"],
        pair_id=cfg["pair_id"],
    )

    return print_report()


if __name__ == "__main__":
    sys.exit(main())
