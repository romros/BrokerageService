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
  selector = GET_OPEN_TRADE_SELECTOR (constant Keccak-256, 4 bytes)
  data = selector + pad32(address) + pad32(uint16) + pad32(uint8)

Categories d'error:
  AUTH_MISSING_ENV     — variable obligatòria absent
  AUTH_INVALID_FORMAT  — format incorrecte
  DNS / CONNECT_TIMEOUT / CONNECT_REFUSED — xarxa
  CHAIN_MISMATCH       — chain_id != OSTIUM_CHAIN_ID
  CONTRACT_REVERT      — eth_call revertida (adreça, chain, params)
  UNEXPECTED_PAYLOAD   — resposta inesperada del RPC

Variables d'entorn:
  OSTIUM_RPC_URL                 (obligatori)
  OSTIUM_CHAIN_ID                (recomanat: 421614=testnet, 42161=mainnet)
  OSTIUM_TRADING_STORAGE_ADDRESS (opcional; si absent es prova NetworkConfig; default = TradingStorage getOpenTrade Trade(9))
  OSTIUM_LEGACY_TRADING_CALL     (opcional; si =1 força eth_call al contract de trading en lloc de TradingStorage)
  OSTIUM_CONTRACT_ADDRESS        (només mode Legacy; default testnet)
  TRADER_ADDRESS / OSTIUM_WALLET_ADDRESS (recomanat; si absent usa 0x0 dummy)
  PAIR_ID / OSTIUM_PAIR_ID       (opcional; default 2)
  INDEX / OSTIUM_INDEX           (opcional; default 0)
  OSTIUM_MARKET_SYMBOL           (opcional; default EURUSD → pair_id=2)
  SMOKE_TIMEOUT                  (default: 5s)

Ús:
  python3 scripts/network_smokes/smoke_ostium_preflight_call.py
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


# ── Constants (font: infrastructure/venues/ostium/ostium_client.py) ───────────

TRADING_CONTRACT_TESTNET = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"
TRADING_CONTRACT_MAINNET = "0x2A9B9c988393f46a2537B0ff11E98c2C15a95afe"  # TODO: verificar mainnet
# Default testnet TradingStorage (no SDK required); mateix patró que TRADING_CONTRACT_TESTNET
DEFAULT_TESTNET_TRADING_STORAGE = "0x0b9F5243B29938668c9Cfbd7557A389EC7Ef88b8"

# Alineat amb core: EURUSD=2 (testnet); PAIR_ID/INDEX via env (default 2, 0).
SYMBOL_TO_PAIR_ID = {
    "EURUSD": 2, "XAUUSD": 1, "BTCUSD": 0, "ETHUSD": 3,
    "GBPUSD": 4, "GBPJPY": 5, "USDJPY": 6, "USDCHF": 7,
    "AUDUSD": 8, "USDCAD": 9,
}
DEFAULT_PAIR_ID = 2
DEFAULT_INDEX = 0

# Legacy: només si l'usuari força OSTIUM_LEGACY_TRADING_CALL=1 (sino default = TradingStorage)
OSTIUM_LEGACY_TRADING_CALL_ENV = "OSTIUM_LEGACY_TRADING_CALL"

CHAIN_IDS = {
    42161: "Arbitrum One (mainnet)",
    421614: "Arbitrum Sepolia (testnet)",
}

# Selector EVM (Keccak-256) de getOpenTrade(address,uint16,uint8). Obtingut amb Web3.keccak al repo (test.sh + requirements).
GET_OPEN_TRADE_SELECTOR_HEX = "4f786488"
GET_OPEN_TRADE_SELECTOR = bytes.fromhex(GET_OPEN_TRADE_SELECTOR_HEX)

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


# ── ABI encoding manual (selector constant + ABI pad32) ────────────────────────


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
      selector (4 bytes, constant GET_OPEN_TRADE_SELECTOR) + address (32 bytes) + uint16 (32 bytes) + uint8 (32 bytes)
    """
    return (
        GET_OPEN_TRADE_SELECTOR
        + _encode_address(trader)
        + _encode_uint(pair_id)
        + _encode_uint(index)
    )


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
    Valida les ENV vars. Retorna dict amb valors resolts (rpc_url, contract, trading_storage, wallet, pair_id, index).
    Default: mode TradingStorage si es pot resoldre; Legacy només si OSTIUM_LEGACY_TRADING_CALL=1.
    """
    print("\n[1] ENV vars Ostium preflight")

    out: dict = {
        "rpc_url": None,
        "chain_id_expected": None,
        "contract": None,
        "trading_storage": None,
        "wallet": None,
        "pair_id": DEFAULT_PAIR_ID,
        "index": DEFAULT_INDEX,
        "storage_mode": False,
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

    # TradingStorage: env → NetworkConfig (si SDK) → default testnet si chain testnet o no definit
    storage = os.environ.get("OSTIUM_TRADING_STORAGE_ADDRESS", "").strip()
    if not storage:
        try:
            from ostium_python_sdk import NetworkConfig  # noqa: PLC0415
            storage = NetworkConfig.testnet().contracts.get("tradingStorage") or ""
        except Exception:
            pass
    if not storage:
        chain_val = out.get("chain_id_expected")
        if chain_val is None or chain_val == 421614:
            storage = DEFAULT_TESTNET_TRADING_STORAGE
            _info("ostium.pf.env.trading_storage", "AUTH_MISSING_ENV",
                  "OSTIUM_TRADING_STORAGE_ADDRESS absent — usant default testnet TradingStorage (no SDK required)",
                  next_action="Opcional: defineix OSTIUM_TRADING_STORAGE_ADDRESS per adreça específica")
    if storage and re.match(r"^0x[0-9a-fA-F]{40}$", storage):
        if storage == DEFAULT_TESTNET_TRADING_STORAGE and not os.environ.get("OSTIUM_TRADING_STORAGE_ADDRESS", "").strip():
            pass  # detail ja a _info abans
        else:
            _pass("ostium.pf.env.trading_storage", f"TradingStorage={storage}")
        out["trading_storage"] = storage
    else:
        out["trading_storage"] = None

    # Mode: Legacy només si l'usuari força OSTIUM_LEGACY_TRADING_CALL=1
    legacy_force = os.environ.get(OSTIUM_LEGACY_TRADING_CALL_ENV, "").strip() == "1"
    out["storage_mode"] = (out["trading_storage"] is not None) and (not legacy_force)

    # OSTIUM_CONTRACT_ADDRESS: només rellevant en mode Legacy; en mode Storage no mostrar INFO/SKIP
    if out["storage_mode"]:
        _skip("ostium.pf.env.contract", "mode TradingStorage")
        out["contract"] = None
    else:
        contract = os.environ.get("OSTIUM_CONTRACT_ADDRESS", "").strip()
        if not contract:
            contract = TRADING_CONTRACT_TESTNET
            _info("ostium.pf.env.contract", "AUTH_MISSING_ENV",
                  "OSTIUM_CONTRACT_ADDRESS absent — usant default testnet (mode Legacy)",
                  next_action="Defineix OSTIUM_CONTRACT_ADDRESS o usa mode TradingStorage sense OSTIUM_LEGACY_TRADING_CALL")
        elif not re.match(r"^0x[0-9a-fA-F]{40}$", contract):
            _fail("ostium.pf.env.contract", "AUTH_INVALID_FORMAT",
                  f"OSTIUM_CONTRACT_ADDRESS format incorrecte: {contract!r}",
                  next_action="L'adreça ha de ser 0x + 40 caràcters hex")
            contract = None
        else:
            _pass("ostium.pf.env.contract", f"OSTIUM_CONTRACT_ADDRESS={contract}")
        out["contract"] = contract

    # Wallet: TRADER_ADDRESS o OSTIUM_WALLET_ADDRESS
    wallet = (os.environ.get("TRADER_ADDRESS", "") or os.environ.get("OSTIUM_WALLET_ADDRESS", "")).strip()
    ZERO_ADDR = "0x" + "0" * 40
    if not wallet:
        wallet = ZERO_ADDR
        _info("ostium.pf.env.wallet", "AUTH_MISSING_ENV",
              "TRADER_ADDRESS/OSTIUM_WALLET_ADDRESS absent — usant 0x0 dummy (getOpenTrade retornarà zeros)",
              next_action="Defineix TRADER_ADDRESS o OSTIUM_WALLET_ADDRESS per veure trades reals")
    elif not re.match(r"^0x[0-9a-fA-F]{40}$", wallet, re.IGNORECASE):
        _fail("ostium.pf.env.wallet", "AUTH_INVALID_FORMAT",
              "TRADER_ADDRESS/OSTIUM_WALLET_ADDRESS format incorrecte",
              next_action="L'adreça ha de ser 0x + 40 caràcters hex")
        wallet = ZERO_ADDR
    else:
        _pass("ostium.pf.env.wallet", f"TRADER_ADDRESS/OSTIUM_WALLET_ADDRESS={wallet[:10]}...")
    out["wallet"] = wallet

    # pair_id: PAIR_ID, després OSTIUM_PAIR_ID, després default 2 (i OSTIUM_MARKET_SYMBOL si no hi ha PAIR_ID/OSTIUM_PAIR_ID)
    pair_id_str = (os.environ.get("PAIR_ID", "") or os.environ.get("OSTIUM_PAIR_ID", "")).strip()
    if pair_id_str:
        try:
            out["pair_id"] = int(pair_id_str)
            _pass("ostium.pf.env.pair_id", f"PAIR_ID/OSTIUM_PAIR_ID={out['pair_id']}")
        except ValueError:
            _fail("ostium.pf.env.pair_id", "AUTH_INVALID_FORMAT",
                  f"PAIR_ID/OSTIUM_PAIR_ID={pair_id_str!r} no és enter",
                  next_action="PAIR_ID o OSTIUM_PAIR_ID ha de ser un enter (ex: 2)")
    else:
        symbol = os.environ.get("OSTIUM_MARKET_SYMBOL", "EURUSD").strip().upper()
        pair_id = SYMBOL_TO_PAIR_ID.get(symbol)
        if pair_id is None:
            out["pair_id"] = DEFAULT_PAIR_ID
            _info("ostium.pf.env.symbol", "AUTH_MISSING_ENV",
                  f"OSTIUM_MARKET_SYMBOL={symbol!r} desconegut — usant pair_id={DEFAULT_PAIR_ID}",
                  next_action="Defineix PAIR_ID=2, OSTIUM_PAIR_ID=2 o OSTIUM_MARKET_SYMBOL=EURUSD")
        else:
            out["pair_id"] = pair_id
            _pass("ostium.pf.env.symbol", f"OSTIUM_MARKET_SYMBOL={symbol} → pair_id={pair_id}")

    # index: INDEX, després OSTIUM_INDEX, després default 0
    index_str = (os.environ.get("INDEX", "") or os.environ.get("OSTIUM_INDEX", str(DEFAULT_INDEX))).strip()
    try:
        out["index"] = int(index_str)
    except ValueError:
        out["index"] = DEFAULT_INDEX
    _pass("ostium.pf.env.index", f"INDEX/OSTIUM_INDEX={out['index']}")

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


# ── Secció 3: eth_call → getOpenTrade (TradingStorage Trade(9) o legacy) ──────

# Trade(9) ABI: 9 × 32 bytes — collateral, openPrice, tp, sl, trader, leverage, pairIndex, index, buy
TRADE9_NUM_WORDS = 9
TRADE9_BYTES = TRADE9_NUM_WORDS * 32


def _decode_trade9(raw: bytes) -> Optional[dict]:
    """Decodifica retorn getOpenTrade TradingStorage (Trade(9)). Retorna dict o None si payload curt."""
    if len(raw) < TRADE9_BYTES:
        return None
    collateral = int.from_bytes(raw[0:32], "big")
    open_price = int.from_bytes(raw[32:64], "big")
    tp = int.from_bytes(raw[64:96], "big")
    sl = int.from_bytes(raw[96:128], "big")
    trader_bytes = raw[128:160]
    trader = "0x" + trader_bytes[-20:].hex() if len(trader_bytes) >= 20 else "0x" + "0" * 40
    leverage = int.from_bytes(raw[160:192], "big")
    pair_index = int.from_bytes(raw[192:224], "big")
    index = int.from_bytes(raw[224:256], "big")
    buy = int.from_bytes(raw[256:288], "big") != 0
    return {
        "collateral": collateral,
        "openPrice": open_price,
        "tp": tp,
        "sl": sl,
        "trader": trader,
        "leverage": leverage,
        "pairIndex": pair_index,
        "index": index,
        "buy": buy,
    }


def check_preflight_call(
    rpc_url: str,
    contract: str,
    wallet: str,
    pair_id: int,
    index: int = 0,
    trading_storage: Optional[str] = None,
) -> None:
    """
    Fa eth_call a getOpenTrade(wallet, pair_id, index) — view, 0 TX.
    Si trading_storage és donat, crida TradingStorage i decodifica Trade(9);
    sinó crida contract (legacy) i decodifica 6 camps.
    Si no hi ha trade obert: imprimeix "no open trade at idx ..." i PASS (no error).
    """
    target = trading_storage or contract
    target_name = "TradingStorage" if trading_storage else "contract"
    print(f"\n[3] eth_call → getOpenTrade({wallet[:10]}..., pair_id={pair_id}, index={index})")
    print(f"    {target_name}: {target}")

    calldata = build_get_open_trade_calldata(wallet, pair_id, index)
    data_hex = "0x" + calldata.hex()

    result_hex, err = _jsonrpc_eth_call(rpc_url, target, data_hex)

    name = "ostium.pf.call.getOpenTrade"

    if err is None:
        detail = "eth_call OK"
        if result_hex and len(result_hex) > 2:
            raw = bytes.fromhex(result_hex.removeprefix("0x"))
            if trading_storage and len(raw) >= TRADE9_BYTES:
                t9 = _decode_trade9(raw)
                if t9:
                    print(f"    getOpenTrade(trader, pair, index): collateral={t9['collateral']} openPrice={t9['openPrice']} pairIndex={t9['pairIndex']} index={t9['index']} trader={t9['trader']}")
                    if t9["collateral"] > 0 and t9["openPrice"] > 0:
                        detail += f" — trade actiu: collateral={t9['collateral']} openPrice={t9['openPrice']} pairIndex={t9['pairIndex']} index={t9['index']} trader={t9['trader']}"
                    else:
                        print(f"    no open trade at idx {index}")
                        detail += f" — no open trade at idx {index}"
            elif len(raw) >= 192:
                collateral_raw = int.from_bytes(raw[96:128], "big")
                is_long_raw = int.from_bytes(raw[160:192], "big")
                if collateral_raw > 0:
                    collateral = collateral_raw / 1e18
                    side = "LONG" if is_long_raw else "SHORT"
                    detail += f" — trade actiu: collateral={collateral:.4f} USDC ({side})"
                else:
                    detail += f" — no open trade at idx {index}"
            else:
                detail += f" — resposta {len(raw)} bytes"
        _pass(name, detail)

    elif err and err.startswith("CONTRACT_REVERT:"):
        revert_msg = err.removeprefix("CONTRACT_REVERT:")
        _fail(name, "CONTRACT_REVERT",
              f"eth_call revertida: {revert_msg}",
              next_action=(
                  "Possible causa: adreça contract/TradingStorage incorrecta, chain errònia, "
                  "o adreça de wallet malformada. Comprova OSTIUM_TRADING_STORAGE_ADDRESS i OSTIUM_CHAIN_ID"
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

    # Target: TradingStorage (storage_mode) o contract (legacy); cal tenir almenys un
    has_target = (cfg.get("trading_storage") is not None) or (cfg.get("contract") is not None)
    if not has_target:
        _skip("ostium.pf.chain_id", "SKIP — cap adreça (TradingStorage ni contract)")
        _skip("ostium.pf.call.getOpenTrade", "SKIP — cap adreça (TradingStorage ni contract)")
        return print_report()

    chain_ok = check_chain(rpc_url, cfg["chain_id_expected"])
    if not chain_ok:
        _skip("ostium.pf.call.getOpenTrade", "SKIP — chain mismatch o RPC inaccessible")
        return print_report()

    check_preflight_call(
        rpc_url=rpc_url,
        contract=cfg.get("contract"),  # None en mode Storage
        wallet=cfg["wallet"],
        pair_id=cfg["pair_id"],
        index=cfg.get("index", DEFAULT_INDEX),
        trading_storage=cfg.get("trading_storage"),
    )

    return print_report()


if __name__ == "__main__":
    sys.exit(main())
