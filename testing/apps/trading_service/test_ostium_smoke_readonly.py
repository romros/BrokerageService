#!/usr/bin/env python3
"""
test_ostium_smoke_readonly.py — Tests 0-network per smoke_ostium_readonly.py

Verifica:
1. ENV absent → categoria AUTH_MISSING_ENV + exit 1
2. Chain mismatch (stub) → categoria CHAIN_MISMATCH + exit 1
3. Subgraph absent → SKIP (no FAIL)
4. --require-subgraph + error subgraph → FAIL

Normes:
- 0-network (cap crida real a RPC ni subgraph)
- Scripts Python purs (asyncio.run si cal, aquí és tot sync)
- Segueix patró del projecte (no pytest)
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importem el mòdul del smoke (path relatiu als scripts)
SMOKE_DIR = ROOT / "scripts" / "network_smokes"
if str(SMOKE_DIR) not in sys.path:
    sys.path.insert(0, str(SMOKE_DIR))


# ── Helper: executar check_env amb env controlada ────────────────────────────


def _run_env_check(env: dict) -> tuple[list, Optional[str]]:
    """
    Executa smoke_ostium_readonly.check_env() amb env simulada.
    Retorna (results, rpc_url).
    """
    import importlib
    import smoke_ostium_readonly as mod

    # Reinicialitzem la llista de resultats (és global al mòdul)
    mod.results.clear()

    with patch.dict(os.environ, env, clear=True):
        rpc_url = mod.check_env()

    return list(mod.results), rpc_url


def _run_rpc_check_stubbed(rpc_url: str, env: dict,
                            block_result=None, block_err=None,
                            chain_result=None, chain_err=None) -> list:
    """
    Executa check_rpc() amb _jsonrpc stubbejat.
    """
    import smoke_ostium_readonly as mod
    mod.results.clear()

    call_count = [0]

    def fake_jsonrpc(url, method, params):
        call_count[0] += 1
        if method == "eth_blockNumber":
            return block_result, block_err
        if method == "eth_chainId":
            return chain_result, chain_err
        return None, "UNEXPECTED_PAYLOAD"

    with patch.dict(os.environ, env, clear=True):
        with patch.object(mod, "_jsonrpc", side_effect=fake_jsonrpc):
            mod.check_rpc(rpc_url)

    return list(mod.results)


def _run_subgraph_check_stubbed(env: dict,
                                 graphql_result=None,
                                 graphql_err=None,
                                 require_subgraph: bool = False) -> list:
    """
    Executa check_subgraph() amb _graphql_post stubbejat.
    """
    import smoke_ostium_readonly as mod
    mod.results.clear()
    mod.REQUIRE_SUBGRAPH = require_subgraph

    def fake_graphql(url, query):
        return graphql_result, graphql_err

    with patch.dict(os.environ, env, clear=True):
        with patch.object(mod, "_graphql_post", side_effect=fake_graphql):
            mod.check_subgraph()

    mod.REQUIRE_SUBGRAPH = False  # reset
    return list(mod.results)


# ── Test 1: ENV absent → AUTH_MISSING_ENV + rpc_url = None ──────────────────


def test_env_rpc_url_missing():
    """OSTIUM_RPC_URL absent → FAIL AUTH_MISSING_ENV, rpc_url=None."""
    results, rpc_url = _run_env_check({})
    rpc_result = next((r for r in results if r.name == "ostium.env.rpc_url"), None)
    assert rpc_result is not None, "Hauria d'haver comprovat ostium.env.rpc_url"
    assert rpc_result.status == "FAIL", f"Esperava FAIL, got {rpc_result.status}"
    assert rpc_result.category == "AUTH_MISSING_ENV", \
        f"Categoria incorrecta: {rpc_result.category}"
    assert rpc_url is None, "rpc_url hauria de ser None si absent"
    print("✓ test_env_rpc_url_missing passed")


# ── Test 2: ENV present però format incorrecte → AUTH_INVALID_FORMAT ─────────


def test_env_rpc_url_invalid_format():
    """OSTIUM_RPC_URL amb format incorrecte (no http/https) → FAIL AUTH_INVALID_FORMAT."""
    results, rpc_url = _run_env_check({"OSTIUM_RPC_URL": "wss://rpc.example.com"})
    rpc_result = next((r for r in results if r.name == "ostium.env.rpc_url"), None)
    assert rpc_result is not None
    assert rpc_result.status == "FAIL", f"Esperava FAIL, got {rpc_result.status}"
    assert rpc_result.category == "AUTH_INVALID_FORMAT", \
        f"Categoria incorrecta: {rpc_result.category}"
    assert rpc_url is None
    print("✓ test_env_rpc_url_invalid_format passed")


# ── Test 3: ENV OK → PASS ─────────────────────────────────────────────────────


def test_env_rpc_url_valid():
    """OSTIUM_RPC_URL vàlida → PASS, rpc_url retornat."""
    rpc = "https://arb-sepolia.g.alchemy.com/v2/FAKE_KEY"
    results, rpc_url = _run_env_check({"OSTIUM_RPC_URL": rpc})
    rpc_result = next((r for r in results if r.name == "ostium.env.rpc_url"), None)
    assert rpc_result is not None
    assert rpc_result.status == "PASS", f"Esperava PASS, got {rpc_result.status}"
    assert rpc_url == rpc
    print("✓ test_env_rpc_url_valid passed")


# ── Test 4: CHAIN_ID absent → INFO (no FAIL) ─────────────────────────────────


def test_env_chain_id_missing_is_info():
    """OSTIUM_CHAIN_ID absent → INFO (no FAIL), no bloqueja."""
    results, _ = _run_env_check({"OSTIUM_RPC_URL": "https://rpc.example.com"})
    chain_result = next((r for r in results if r.name == "ostium.env.chain_id"), None)
    assert chain_result is not None
    assert chain_result.status == "INFO", \
        f"Esperava INFO (no FAIL), got {chain_result.status}"
    print("✓ test_env_chain_id_missing_is_info passed")


# ── Test 5: RPC chain mismatch → FAIL CHAIN_MISMATCH ─────────────────────────


def test_rpc_chain_mismatch():
    """RPC retorna chain_id=42161 però OSTIUM_CHAIN_ID=421614 → FAIL CHAIN_MISMATCH."""
    # block=0x1234 (liveness OK), chain=0xa4b1 (42161=mainnet)
    results = _run_rpc_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={"OSTIUM_CHAIN_ID": "421614"},  # esperat testnet
        block_result="0x1234", block_err=None,
        chain_result=hex(42161), chain_err=None,  # retorna mainnet
    )
    chain_res = next((r for r in results if r.name == "ostium.rpc.chain_id"), None)
    assert chain_res is not None, "Hauria d'haver comprovat chain_id"
    assert chain_res.status == "FAIL", f"Esperava FAIL, got {chain_res.status}"
    assert chain_res.category == "CHAIN_MISMATCH", \
        f"Categoria incorrecta: {chain_res.category}"
    print("✓ test_rpc_chain_mismatch passed")


# ── Test 6: RPC chain coincideix → PASS ──────────────────────────────────────


def test_rpc_chain_match():
    """RPC retorna chain_id=421614 i OSTIUM_CHAIN_ID=421614 → PASS."""
    results = _run_rpc_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={"OSTIUM_CHAIN_ID": "421614"},
        block_result="0x1234", block_err=None,
        chain_result=hex(421614), chain_err=None,
    )
    chain_res = next((r for r in results if r.name == "ostium.rpc.chain_id"), None)
    assert chain_res is not None
    assert chain_res.status == "PASS", f"Esperava PASS, got {chain_res.status}"
    print("✓ test_rpc_chain_match passed")


# ── Test 7: RPC down → FAIL + chain SKIP ─────────────────────────────────────


def test_rpc_liveness_fail_skips_chain():
    """RPC no respon (CONNECT_REFUSED) → FAIL liveness + SKIP chain_id."""
    results = _run_rpc_check_stubbed(
        rpc_url="https://rpc.example.com",
        env={},
        block_result=None, block_err="CONNECT_REFUSED",
        chain_result=None, chain_err=None,
    )
    liveness = next((r for r in results if r.name == "ostium.rpc.liveness"), None)
    chain = next((r for r in results if r.name == "ostium.rpc.chain_id"), None)
    assert liveness is not None and liveness.status == "FAIL", \
        f"Esperava FAIL liveness, got {liveness}"
    assert chain is not None and chain.status == "SKIP", \
        f"Esperava SKIP chain, got {chain}"
    print("✓ test_rpc_liveness_fail_skips_chain passed")


# ── Test 8: Subgraph absent → SKIP ───────────────────────────────────────────


def test_subgraph_url_missing_is_skip():
    """OSTIUM_SUBGRAPH_URL absent → SKIP subgraph probe (no FAIL)."""
    import smoke_ostium_readonly as mod
    mod.results.clear()
    with patch.dict(os.environ, {}, clear=True):
        mod.check_subgraph()
    # No hauria d'afegir cap resultat (SKIP és implícit per print)
    # O pot afegir un SKIP — en qualsevol cas cap FAIL
    fail = [r for r in mod.results if r.status == "FAIL"]
    assert len(fail) == 0, f"No hauria d'haver FAILs si subgraph absent: {fail}"
    print("✓ test_subgraph_url_missing_is_skip passed")


# ── Test 9: Subgraph error (default) → INFO, no FAIL ─────────────────────────


def test_subgraph_error_default_is_info():
    """Error de xarxa al subgraph (default) → INFO, no FAIL."""
    results = _run_subgraph_check_stubbed(
        env={"OSTIUM_SUBGRAPH_URL": "https://subgraph.example.com"},
        graphql_result=None,
        graphql_err="CONNECT_TIMEOUT",
        require_subgraph=False,
    )
    sg = next((r for r in results if r.name == "ostium.subgraph"), None)
    assert sg is not None
    assert sg.status == "INFO", f"Esperava INFO (no FAIL per defecte), got {sg.status}"
    print("✓ test_subgraph_error_default_is_info passed")


# ── Test 10: Subgraph error + --require-subgraph → FAIL ──────────────────────


def test_subgraph_error_require_is_fail():
    """Error subgraph + --require-subgraph → FAIL."""
    results = _run_subgraph_check_stubbed(
        env={"OSTIUM_SUBGRAPH_URL": "https://subgraph.example.com"},
        graphql_result=None,
        graphql_err="CONNECT_TIMEOUT",
        require_subgraph=True,
    )
    sg = next((r for r in results if r.name == "ostium.subgraph"), None)
    assert sg is not None
    assert sg.status == "FAIL", f"Esperava FAIL amb --require-subgraph, got {sg.status}"
    print("✓ test_subgraph_error_require_is_fail passed")


# ── Test 11: Subgraph STALE (openTrades absent) → INFO per defecte ───────────


def test_subgraph_stale_is_info():
    """Subgraph respon però openTrades absent → INFO SUBGRAPH_STALE (no FAIL)."""
    fake_response = {"data": {}}  # openTrades absent
    results = _run_subgraph_check_stubbed(
        env={"OSTIUM_SUBGRAPH_URL": "https://subgraph.example.com"},
        graphql_result=fake_response,
        graphql_err=None,
        require_subgraph=False,
    )
    sg = next((r for r in results if r.name == "ostium.subgraph"), None)
    assert sg is not None
    assert sg.status == "INFO", f"Esperava INFO per stale, got {sg.status}"
    assert sg.category == "SUBGRAPH_STALE", f"Categoria incorrecta: {sg.category}"
    print("✓ test_subgraph_stale_is_info passed")


# ── Test 12: Subgraph OK → PASS ──────────────────────────────────────────────


def test_subgraph_ok_is_pass():
    """Subgraph respon amb openTrades → PASS."""
    fake_response = {"data": {"openTrades": []}}
    results = _run_subgraph_check_stubbed(
        env={"OSTIUM_SUBGRAPH_URL": "https://subgraph.example.com"},
        graphql_result=fake_response,
        graphql_err=None,
        require_subgraph=False,
    )
    sg = next((r for r in results if r.name == "ostium.subgraph"), None)
    assert sg is not None
    assert sg.status == "PASS", f"Esperava PASS, got {sg.status}"
    print("✓ test_subgraph_ok_is_pass passed")


# ── Main ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_env_rpc_url_missing,
        test_env_rpc_url_invalid_format,
        test_env_rpc_url_valid,
        test_env_chain_id_missing_is_info,
        test_rpc_chain_mismatch,
        test_rpc_chain_match,
        test_rpc_liveness_fail_skips_chain,
        test_subgraph_url_missing_is_skip,
        test_subgraph_error_default_is_info,
        test_subgraph_error_require_is_fail,
        test_subgraph_stale_is_info,
        test_subgraph_ok_is_pass,
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
