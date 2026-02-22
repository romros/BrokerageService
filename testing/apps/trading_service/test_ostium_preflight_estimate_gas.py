#!/usr/bin/env python3
"""
test_ostium_preflight_estimate_gas.py — Tests 0-network per smoke_ostium_preflight_estimate_gas.py

Verifica:
1. ENV absent (OSTIUM_RPC_URL, OSTIUM_CONTRACT_ADDRESS, OSTIUM_FROM_ADDRESS) → FAIL AUTH_MISSING_ENV
2. ENV format invàlid (rpc_url, contract, from_address) → FAIL AUTH_INVALID_FORMAT
3. Chain mismatch (stub) → FAIL CHAIN_MISMATCH
4. eth_estimateGas OK (mock) → PASS
5. eth_estimateGas CONTRACT_REVERT (mock) → FAIL CONTRACT_REVERT
6. eth_estimateGas error xarxa → FAIL (CONNECT_TIMEOUT o similar)

Normes: 0-network (cap crida real). Segueix patró test_ostium_preflight_call.py.
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


def _run_env_check(env: dict) -> tuple[list, dict]:
    """Executa check_env() amb env simulada. Retorna (results, cfg)."""
    import smoke_ostium_preflight_estimate_gas as mod
    mod.results.clear()
    with patch.dict(os.environ, env, clear=True):
        cfg = mod.check_env()
    return list(mod.results), cfg


def _run_chain_check_stubbed(rpc_url: str, env: dict,
                             chain_result=None, chain_err=None) -> list:
    import smoke_ostium_preflight_estimate_gas as mod
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


def _run_estimate_gas_stubbed(
    rpc_url: str, from_addr: str, to_addr: str, calldata_hex: str,
    est_result: Optional[str] = None, est_err: Optional[str] = None,
) -> list:
    import smoke_ostium_preflight_estimate_gas as mod
    mod.results.clear()

    def fake_estimate_gas(url, from_a, to_a, data_hex, value_hex="0x0"):
        return est_result, est_err

    with patch.object(mod, "_jsonrpc_estimate_gas", side_effect=fake_estimate_gas):
        mod.check_estimate_gas(rpc_url, from_addr, to_addr, calldata_hex)
    return list(mod.results)


# ── Test 1: OSTIUM_RPC_URL absent → FAIL AUTH_MISSING_ENV ────────────────────


def test_env_rpc_url_missing():
    """OSTIUM_RPC_URL absent → FAIL AUTH_MISSING_ENV."""
    results, cfg = _run_env_check({})
    r = next((x for x in results if x.name == "ostium.eg.env.rpc_url"), None)
    assert r is not None
    assert r.status == "FAIL", f"Esperava FAIL, got {r.status}"
    assert r.category == "AUTH_MISSING_ENV"
    assert cfg["rpc_url"] is None
    print("✓ test_env_rpc_url_missing passed")


# ── Test 2: RPC_URL format incorrecte → FAIL AUTH_INVALID_FORMAT ─────────────────


def test_env_rpc_url_invalid_format():
    """OSTIUM_RPC_URL wss:// → FAIL AUTH_INVALID_FORMAT."""
    results, _ = _run_env_check({"OSTIUM_RPC_URL": "wss://rpc.example.com"})
    r = next((x for x in results if x.name == "ostium.eg.env.rpc_url"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "AUTH_INVALID_FORMAT"
    print("✓ test_env_rpc_url_invalid_format passed")


# ── Test 3: OSTIUM_CONTRACT_ADDRESS absent → FAIL AUTH_MISSING_ENV ────────────


def test_env_contract_missing():
    """OSTIUM_CONTRACT_ADDRESS absent → FAIL AUTH_MISSING_ENV."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_FROM_ADDRESS": "0x" + "a" * 40,
    })
    r = next((x for x in results if x.name == "ostium.eg.env.contract"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "AUTH_MISSING_ENV"
    assert cfg["contract"] is None
    print("✓ test_env_contract_missing passed")


# ── Test 4: OSTIUM_CONTRACT_ADDRESS format incorrecte → AUTH_INVALID_FORMAT ───


def test_env_contract_invalid_format():
    """OSTIUM_CONTRACT_ADDRESS no 0x40hex → FAIL AUTH_INVALID_FORMAT."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_CONTRACT_ADDRESS": "not-an-address",
        "OSTIUM_FROM_ADDRESS": "0x" + "a" * 40,
    })
    r = next((x for x in results if x.name == "ostium.eg.env.contract"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "AUTH_INVALID_FORMAT"
    assert cfg["contract"] is None
    print("✓ test_env_contract_invalid_format passed")


# ── Test 5: OSTIUM_FROM_ADDRESS absent → FAIL AUTH_MISSING_ENV ──────────────────


def test_env_from_address_missing():
    """OSTIUM_FROM_ADDRESS absent → FAIL AUTH_MISSING_ENV."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_CONTRACT_ADDRESS": "0x" + "b" * 40,
    })
    r = next((x for x in results if x.name == "ostium.eg.env.from_address"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "AUTH_MISSING_ENV"
    assert cfg["from_address"] is None
    print("✓ test_env_from_address_missing passed")


# ── Test 6: OSTIUM_FROM_ADDRESS format incorrecte → AUTH_INVALID_FORMAT ────────


def test_env_from_address_invalid_format():
    """OSTIUM_FROM_ADDRESS no 0x40hex → FAIL AUTH_INVALID_FORMAT."""
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_CONTRACT_ADDRESS": "0x" + "b" * 40,
        "OSTIUM_FROM_ADDRESS": "not-a-wallet",
    })
    r = next((x for x in results if x.name == "ostium.eg.env.from_address"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "AUTH_INVALID_FORMAT"
    assert cfg["from_address"] is None
    print("✓ test_env_from_address_invalid_format passed")


# ── Test 7: ENV ok → cfg complet ──────────────────────────────────────────────


def test_env_all_valid():
    """ENV vàlida → cap FAIL a env, cfg complet."""
    from_addr = "0x" + "a" * 40
    contract = "0x" + "b" * 40
    results, cfg = _run_env_check({
        "OSTIUM_RPC_URL": "https://rpc.example.com",
        "OSTIUM_CHAIN_ID": "421614",
        "OSTIUM_CONTRACT_ADDRESS": contract,
        "OSTIUM_FROM_ADDRESS": from_addr,
        "OSTIUM_MARKET_SYMBOL": "XAUUSD",
    })
    fails = [r for r in results if r.status == "FAIL"]
    assert len(fails) == 0, f"No hauria d'haver FAILs: {fails}"
    assert cfg["rpc_url"] == "https://rpc.example.com"
    assert cfg["contract"] == contract
    assert cfg["from_address"] == from_addr
    assert cfg["pair_id"] == 1
    assert cfg["chain_id_expected"] == 421614
    print("✓ test_env_all_valid passed")


# ── Test 8: Chain mismatch → FAIL CHAIN_MISMATCH ──────────────────────────────


def test_chain_mismatch():
    """RPC retorna chain 42161, OSTIUM_CHAIN_ID=421614 → FAIL CHAIN_MISMATCH."""
    results = _run_chain_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={"OSTIUM_CHAIN_ID": "421614"},
        chain_result=hex(42161), chain_err=None,
    )
    r = next((x for x in results if x.name == "ostium.eg.rpc.chain_id"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "CHAIN_MISMATCH"
    print("✓ test_chain_mismatch passed")


# ── Test 9: Chain OK → PASS ────────────────────────────────────────────────────


def test_chain_match():
    """RPC retorna chain 421614, OSTIUM_CHAIN_ID=421614 → PASS."""
    results = _run_chain_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={"OSTIUM_CHAIN_ID": "421614"},
        chain_result=hex(421614), chain_err=None,
    )
    r = next((x for x in results if x.name == "ostium.eg.rpc.chain_id"), None)
    assert r is not None
    assert r.status == "PASS"
    print("✓ test_chain_match passed")


# ── Test 10: eth_estimateGas OK → PASS ────────────────────────────────────────


def test_estimate_gas_ok():
    """eth_estimateGas retorna result hex → PASS."""
    from_addr = "0x" + "0" * 40
    to_addr = "0x" + "2" * 40
    calldata_hex = "0x4f786488" + "00" * 96  # 4 + 32*3
    results = _run_estimate_gas_stubbed(
        rpc_url="https://rpc.example.com",
        from_addr=from_addr,
        to_addr=to_addr,
        calldata_hex=calldata_hex,
        est_result="0x5208",  # 21000
        est_err=None,
    )
    r = next((x for x in results if x.name == "ostium.eg.rpc.estimate_gas"), None)
    assert r is not None
    assert r.status == "PASS", f"Esperava PASS, got {r.status}"
    print("✓ test_estimate_gas_ok passed")


# ── Test 11: eth_estimateGas CONTRACT_REVERT → FAIL CONTRACT_REVERT ───────────


def test_estimate_gas_contract_revert():
    """eth_estimateGas error revert → FAIL CONTRACT_REVERT."""
    from_addr = "0x" + "0" * 40
    to_addr = "0x" + "2" * 40
    calldata_hex = "0x4f786488" + "00" * 96
    results = _run_estimate_gas_stubbed(
        rpc_url="https://rpc.example.com",
        from_addr=from_addr,
        to_addr=to_addr,
        calldata_hex=calldata_hex,
        est_result=None,
        est_err="CONTRACT_REVERT:execution reverted",
    )
    r = next((x for x in results if x.name == "ostium.eg.rpc.estimate_gas"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "CONTRACT_REVERT"
    print("✓ test_estimate_gas_contract_revert passed")


# ── Test 12: eth_estimateGas error xarxa → FAIL ───────────────────────────────


def test_estimate_gas_network_error():
    """eth_estimateGas error xarxa → FAIL CONNECT_TIMEOUT (o similar)."""
    from_addr = "0x" + "0" * 40
    to_addr = "0x" + "2" * 40
    calldata_hex = "0x4f786488" + "00" * 96
    results = _run_estimate_gas_stubbed(
        rpc_url="https://rpc.example.com",
        from_addr=from_addr,
        to_addr=to_addr,
        calldata_hex=calldata_hex,
        est_result=None,
        est_err="CONNECT_TIMEOUT",
    )
    r = next((x for x in results if x.name == "ostium.eg.rpc.estimate_gas"), None)
    assert r is not None
    assert r.status == "FAIL"
    assert r.category == "CONNECT_TIMEOUT"
    print("✓ test_estimate_gas_network_error passed")


# ── Main ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_env_rpc_url_missing,
        test_env_rpc_url_invalid_format,
        test_env_contract_missing,
        test_env_contract_invalid_format,
        test_env_from_address_missing,
        test_env_from_address_invalid_format,
        test_env_all_valid,
        test_chain_mismatch,
        test_chain_match,
        test_estimate_gas_ok,
        test_estimate_gas_contract_revert,
        test_estimate_gas_network_error,
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
