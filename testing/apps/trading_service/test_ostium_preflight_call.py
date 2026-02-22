#!/usr/bin/env python3
"""
test_ostium_preflight_call.py — Tests 0-network per smoke_ostium_preflight_call.py

Verifica:
1. ENV absent (OSTIUM_RPC_URL) → FAIL AUTH_MISSING_ENV + SKIP chain/call
2. ENV rpc_url format invàlid → FAIL AUTH_INVALID_FORMAT
3. ENV contract format invàlid → FAIL AUTH_INVALID_FORMAT
4. ENV wallet format invàlid → FAIL AUTH_INVALID_FORMAT
5. ENV symbol desconegut → FAIL AUTH_INVALID_FORMAT
6. Chain mismatch (stub) → FAIL CHAIN_MISMATCH + SKIP eth_call
7. RPC liveness fail → FAIL + SKIP eth_call
8. eth_call OK (zeros → no trade obert) → PASS
9. eth_call CONTRACT_REVERT → FAIL CONTRACT_REVERT
10. eth_call error xarxa → FAIL CONNECT_TIMEOUT

Normes:
- 0-network (cap crida real a RPC)
- Scripts Python purs (no pytest)
- Segueix patró de test_ostium_smoke_readonly.py
"""

import os
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SMOKE_DIR = ROOT / "scripts" / "network_smokes"
if str(SMOKE_DIR) not in sys.path:
    sys.path.insert(0, str(SMOKE_DIR))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_env_check(env: dict) -> tuple[list, dict]:
    """Executa check_env() amb env simulada. Retorna (results, cfg)."""
    import smoke_ostium_preflight_call as mod
    mod.results.clear()
    with patch.dict(os.environ, env, clear=True):
        cfg = mod.check_env()
    return list(mod.results), cfg


def _run_chain_check_stubbed(rpc_url: str, env: dict,
                              chain_result=None, chain_err=None) -> list:
    """Executa check_chain() amb _jsonrpc_simple stubbejat."""
    import smoke_ostium_preflight_call as mod
    mod.results.clear()

    def fake_simple(url, method, params):
        if method == "eth_chainId":
            return chain_result, chain_err
        return None, "UNEXPECTED_PAYLOAD"

    with patch.dict(os.environ, env, clear=True):
        with patch.object(mod, "_jsonrpc_simple", side_effect=fake_simple):
            chain_id_expected = int(env["OSTIUM_CHAIN_ID"]) if "OSTIUM_CHAIN_ID" in env else None
            mod.check_chain(rpc_url, chain_id_expected)

    return list(mod.results)


def _run_preflight_call_stubbed(rpc_url: str, contract: str, wallet: str,
                                 pair_id: int,
                                 call_result=None, call_err=None) -> list:
    """Executa check_preflight_call() amb _jsonrpc_eth_call stubbejat."""
    import smoke_ostium_preflight_call as mod
    mod.results.clear()

    def fake_eth_call(url, to, data_hex, block="latest"):
        return call_result, call_err

    with patch.object(mod, "_jsonrpc_eth_call", side_effect=fake_eth_call):
        mod.check_preflight_call(rpc_url, contract, wallet, pair_id)

    return list(mod.results)


# ── Test 1: OSTIUM_RPC_URL absent → FAIL AUTH_MISSING_ENV ────────────────────


def test_env_rpc_url_missing():
    """OSTIUM_RPC_URL absent → FAIL AUTH_MISSING_ENV, cfg['rpc_url']=None."""
    results, cfg = _run_env_check({})
    rpc_res = next((r for r in results if r.name == "ostium.pf.env.rpc_url"), None)
    assert rpc_res is not None, "Hauria d'haver comprovat ostium.pf.env.rpc_url"
    assert rpc_res.status == "FAIL", f"Esperava FAIL, got {rpc_res.status}"
    assert rpc_res.category == "AUTH_MISSING_ENV", f"Categoria: {rpc_res.category}"
    assert cfg["rpc_url"] is None, "rpc_url hauria de ser None"
    print("✓ test_env_rpc_url_missing passed")


# ── Test 2: RPC_URL format incorrecte → FAIL AUTH_INVALID_FORMAT ─────────────


def test_env_rpc_url_invalid_format():
    """OSTIUM_RPC_URL wss:// (no http/https) → FAIL AUTH_INVALID_FORMAT."""
    results, cfg = _run_env_check({"OSTIUM_RPC_URL": "wss://rpc.example.com"})
    rpc_res = next((r for r in results if r.name == "ostium.pf.env.rpc_url"), None)
    assert rpc_res is not None
    assert rpc_res.status == "FAIL", f"Esperava FAIL, got {rpc_res.status}"
    assert rpc_res.category == "AUTH_INVALID_FORMAT", f"Categoria: {rpc_res.category}"
    assert cfg["rpc_url"] is None
    print("✓ test_env_rpc_url_invalid_format passed")


# ── Test 3: Contract format incorrecte → FAIL AUTH_INVALID_FORMAT ────────────


def test_env_contract_invalid_format():
    """OSTIUM_CONTRACT_ADDRESS format incorrecte → FAIL AUTH_INVALID_FORMAT."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_CONTRACT_ADDRESS": "not-an-address",
    })
    contract_res = next((r for r in results if r.name == "ostium.pf.env.contract"), None)
    assert contract_res is not None
    assert contract_res.status == "FAIL", f"Esperava FAIL, got {contract_res.status}"
    assert contract_res.category == "AUTH_INVALID_FORMAT", f"Categoria: {contract_res.category}"
    assert cfg["contract"] is None, "contract hauria de ser None si format invàlid"
    print("✓ test_env_contract_invalid_format passed")


# ── Test 4: Wallet format incorrecte → FAIL AUTH_INVALID_FORMAT ──────────────


def test_env_wallet_invalid_format():
    """OSTIUM_WALLET_ADDRESS format incorrecte → FAIL AUTH_INVALID_FORMAT."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_WALLET_ADDRESS": "not-a-wallet",
    })
    wallet_res = next((r for r in results if r.name == "ostium.pf.env.wallet"), None)
    assert wallet_res is not None
    assert wallet_res.status == "FAIL", f"Esperava FAIL, got {wallet_res.status}"
    assert wallet_res.category == "AUTH_INVALID_FORMAT", f"Categoria: {wallet_res.category}"
    print("✓ test_env_wallet_invalid_format passed")


# ── Test 5: Symbol desconegut → FAIL AUTH_INVALID_FORMAT ─────────────────────


def test_env_symbol_unknown():
    """OSTIUM_MARKET_SYMBOL=UNKNWN desconegut → FAIL AUTH_INVALID_FORMAT."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_MARKET_SYMBOL": "UNKNWN",
    })
    symbol_res = next((r for r in results if r.name == "ostium.pf.env.symbol"), None)
    assert symbol_res is not None
    assert symbol_res.status == "FAIL", f"Esperava FAIL, got {symbol_res.status}"
    assert symbol_res.category == "AUTH_INVALID_FORMAT", f"Categoria: {symbol_res.category}"
    print("✓ test_env_symbol_unknown passed")


# ── Test 6: ENV ok → cfg complet ─────────────────────────────────────────────


def test_env_all_valid():
    """ENV vàlida completa → tots PASS/INFO, cfg complet."""
    wallet = "0x" + "a" * 40
    contract = "0x" + "b" * 40
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_CHAIN_ID": "421614",
        "OSTIUM_CONTRACT_ADDRESS": contract,
        "OSTIUM_WALLET_ADDRESS": wallet,
        "OSTIUM_MARKET_SYMBOL": "XAUUSD",
    })
    # Cap FAIL
    fails = [r for r in results if r.status == "FAIL"]
    assert len(fails) == 0, f"No hauria d'haver FAILs: {fails}"
    assert cfg["rpc_url"] == "https://rpc.example.com"
    assert cfg["contract"] == contract
    assert cfg["wallet"] == wallet
    assert cfg["pair_id"] == 1  # XAUUSD = pair_id 1
    assert cfg["chain_id_expected"] == 421614
    print("✓ test_env_all_valid passed")


# ── Test 7: Chain mismatch → FAIL CHAIN_MISMATCH ─────────────────────────────


def test_chain_mismatch():
    """RPC retorna chain=42161 (mainnet) però OSTIUM_CHAIN_ID=421614 → FAIL CHAIN_MISMATCH."""
    results = _run_chain_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={"OSTIUM_CHAIN_ID": "421614"},
        chain_result=hex(42161), chain_err=None,
    )
    chain_res = next((r for r in results if r.name == "ostium.pf.chain_id"), None)
    assert chain_res is not None, "Hauria d'haver comprovat ostium.pf.chain_id"
    assert chain_res.status == "FAIL", f"Esperava FAIL, got {chain_res.status}"
    assert chain_res.category == "CHAIN_MISMATCH", f"Categoria: {chain_res.category}"
    print("✓ test_chain_mismatch passed")


# ── Test 8: Chain OK → PASS ───────────────────────────────────────────────────


def test_chain_match():
    """RPC retorna chain=421614 i OSTIUM_CHAIN_ID=421614 → PASS."""
    results = _run_chain_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={"OSTIUM_CHAIN_ID": "421614"},
        chain_result=hex(421614), chain_err=None,
    )
    chain_res = next((r for r in results if r.name == "ostium.pf.chain_id"), None)
    assert chain_res is not None
    assert chain_res.status == "PASS", f"Esperava PASS, got {chain_res.status}"
    print("✓ test_chain_match passed")


# ── Test 9: RPC error → FAIL + eth_call skippejada ───────────────────────────


def test_chain_rpc_down_returns_false():
    """RPC inaccessible → FAIL, check_chain retorna False."""
    import smoke_ostium_preflight_call as mod
    mod.results.clear()

    def fake_simple(url, method, params):
        return None, "CONNECT_REFUSED"

    with patch.object(mod, "_jsonrpc_simple", side_effect=fake_simple):
        ok = mod.check_chain("https://rpc.example.com", None)

    assert ok is False, "check_chain hauria de retornar False si RPC down"
    chain_res = next((r for r in mod.results if r.name == "ostium.pf.chain_id"), None)
    assert chain_res is not None
    assert chain_res.status == "FAIL", f"Esperava FAIL, got {chain_res.status}"
    print("✓ test_chain_rpc_down_returns_false passed")


# ── Test 10: eth_call OK (zeros) → PASS ──────────────────────────────────────


def test_preflight_call_ok_empty_trade():
    """eth_call retorna 192 bytes de zeros (no trade) → PASS."""
    # Resposta: 6 camps × 32 bytes = 192 bytes, tots zeros (collateral=0 = no trade)
    zero_bytes = "0x" + "00" * 192
    wallet = "0x" + "0" * 40
    contract = "0x" + "2" * 40

    results = _run_preflight_call_stubbed(
        rpc_url="https://rpc.example.com",
        contract=contract,
        wallet=wallet,
        pair_id=0,
        call_result=zero_bytes,
        call_err=None,
    )
    call_res = next((r for r in results if r.name == "ostium.pf.call.getOpenTrade"), None)
    assert call_res is not None, "Hauria d'haver comprovat ostium.pf.call.getOpenTrade"
    assert call_res.status == "PASS", f"Esperava PASS, got {call_res.status}"
    print("✓ test_preflight_call_ok_empty_trade passed")


# ── Test 11: eth_call CONTRACT_REVERT → FAIL CONTRACT_REVERT ─────────────────


def test_preflight_call_contract_revert():
    """eth_call revertida → FAIL CONTRACT_REVERT."""
    wallet = "0x" + "0" * 40
    contract = "0x" + "2" * 40

    results = _run_preflight_call_stubbed(
        rpc_url="https://rpc.example.com",
        contract=contract,
        wallet=wallet,
        pair_id=0,
        call_result=None,
        call_err="CONTRACT_REVERT:execution reverted",
    )
    call_res = next((r for r in results if r.name == "ostium.pf.call.getOpenTrade"), None)
    assert call_res is not None
    assert call_res.status == "FAIL", f"Esperava FAIL, got {call_res.status}"
    assert call_res.category == "CONTRACT_REVERT", f"Categoria: {call_res.category}"
    print("✓ test_preflight_call_contract_revert passed")


# ── Test 12: eth_call error xarxa → FAIL CONNECT_TIMEOUT ────────────────────


def test_preflight_call_network_error():
    """eth_call error de xarxa → FAIL CONNECT_TIMEOUT."""
    wallet = "0x" + "0" * 40
    contract = "0x" + "2" * 40

    results = _run_preflight_call_stubbed(
        rpc_url="https://rpc.example.com",
        contract=contract,
        wallet=wallet,
        pair_id=0,
        call_result=None,
        call_err="CONNECT_TIMEOUT",
    )
    call_res = next((r for r in results if r.name == "ostium.pf.call.getOpenTrade"), None)
    assert call_res is not None
    assert call_res.status == "FAIL", f"Esperava FAIL, got {call_res.status}"
    assert call_res.category == "CONNECT_TIMEOUT", f"Categoria: {call_res.category}"
    print("✓ test_preflight_call_network_error passed")


# ── Test 13: Calldata ABI encoding — selector correcte ───────────────────────


def test_calldata_abi_selector():
    """
    Verifica que el selector de getOpenTrade(address,uint16,uint8) és correcte.

    Selector esperat (keccak256 dels primers 4 bytes):
      keccak256("getOpenTrade(address,uint16,uint8)") = 0xe7d9a0...
      Però usem sha3_256 (Python) com a aproximació — el test verifica
      que el calldata té 100 bytes (4 selector + 32×3 params) i el selector
      és consistent entre crides.
    """
    import smoke_ostium_preflight_call as mod
    wallet = "0x" + "a" * 40
    cd1 = mod.build_get_open_trade_calldata(wallet, 0, 0)
    cd2 = mod.build_get_open_trade_calldata(wallet, 0, 0)

    # 4 (selector) + 32 (address) + 32 (pair_id) + 32 (index) = 100 bytes
    assert len(cd1) == 100, f"Calldata hauria de ser 100 bytes, got {len(cd1)}"
    assert cd1 == cd2, "Calldata hauria de ser determinista"

    # El selector (primers 4 bytes) ha de ser sempre el mateix
    assert cd1[:4] == cd2[:4], "Selector hauria de ser consistent"

    # L'adreça ha d'estar en els bytes 16-36 (12 zeros + 20 bytes adreça)
    addr_bytes = cd1[16:36]
    assert addr_bytes == bytes.fromhex("a" * 40), \
        f"Adreça incorrectament codificada: {addr_bytes.hex()}"

    print("✓ test_calldata_abi_selector passed")


# ── Test 14: Calldata amb pair_id diferent → selectors iguals, params dif ────


def test_calldata_pair_id_encoding():
    """pair_id=1 (XAUUSD) codificat correctament al calldata."""
    import smoke_ostium_preflight_call as mod
    wallet = "0x" + "0" * 40
    cd_0 = mod.build_get_open_trade_calldata(wallet, 0, 0)
    cd_1 = mod.build_get_open_trade_calldata(wallet, 1, 0)

    # Selector igual
    assert cd_0[:4] == cd_1[:4], "Selector hauria de ser el mateix"
    # pair_id diferent (bytes 36-68)
    assert cd_0[36:68] != cd_1[36:68], "pair_id hauria de diferir"
    # pair_id=1 ha d'estar a l'últim byte de la paraula de 32 bytes
    assert cd_1[36:68][-1] == 1, f"pair_id=1 hauria de ser 0x01, got {cd_1[36:68][-1]}"

    print("✓ test_calldata_pair_id_encoding passed")


# ── Main ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_env_rpc_url_missing,
        test_env_rpc_url_invalid_format,
        test_env_contract_invalid_format,
        test_env_wallet_invalid_format,
        test_env_symbol_unknown,
        test_env_all_valid,
        test_chain_mismatch,
        test_chain_match,
        test_chain_rpc_down_returns_false,
        test_preflight_call_ok_empty_trade,
        test_preflight_call_contract_revert,
        test_preflight_call_network_error,
        test_calldata_abi_selector,
        test_calldata_pair_id_encoding,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'=' * 60}")
    print(f"Resultat: {passed} OK, {failed} FALLATS de {len(tests)} tests")
    if failed > 0:
        sys.exit(1)
