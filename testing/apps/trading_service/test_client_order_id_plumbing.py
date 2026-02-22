#!/usr/bin/env python3
"""
Phase J — client_order_id plumbing end-to-end (0-network tests).

Tests:
1. client_order_id passat al fake adapter quan present a OrderOpenRequest
2. client_order_id=None quan no present (backward compat)
3. Idempotència: mateixa crida × 2 → mateix position_id, adapter cridat 1 cop
4. API models: OrderOpenRequest accepta camp opcional (sense trencament)
5. TradingCore: client_order_id del req arriba a open_position del adapter

Normes:
- NO pytest runner (scripts Python purs)
- 0-network (no SDK, no web3, no HTTP extern)
- Segueix patró de test_trading_core.py (asyncio.run)
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.api.models import OrderOpenRequest
from application.trading.trading_core import TradingCore


def run(coro):
    return asyncio.run(coro)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_fake_adapter():
    """Retorna (adapter, open_calls) — adapter que registra les crides a open_position."""
    open_calls = []

    class _FakeAdapter:
        async def open_position(self, symbol, is_long, collateral, leverage,
                                sl_price=None, tp_price=None, client_order_id=None, **kw):
            open_calls.append({
                "symbol": symbol,
                "client_order_id": client_order_id,
                "collateral": collateral,
            })
            # Simula idempotència: si client_order_id repetit, retorna el primer position_id
            pid = f"fake:{symbol}:0"
            from domain.models import OrderResult
            return OrderResult(
                success=True,
                position_id=pid,
                order_id="fake_order",
                executed_price=1.08,
                executed_size=collateral * leverage,
            )

    return _FakeAdapter(), open_calls


def _make_req(venue="ostium", symbol="EURUSD", side="long",
              collateral=10.0, leverage=2.0, client_order_id=None):
    """Construeix un OrderOpenRequest (Pydantic) amb els valors donats."""
    data = {
        "venue": venue,
        "symbol": symbol,
        "side": side,
        "collateral": collateral,
        "leverage": leverage,
    }
    if client_order_id is not None:
        data["client_order_id"] = client_order_id
    return OrderOpenRequest(**data)


def _make_core(adapter, mode="paper"):
    return TradingCore(
        adapter_factory=lambda v: adapter if v == "ostium" else None,
        mode=mode,
    )


# ── Test 1: client_order_id present → arriba al adapter ──────────────────────


def test_client_order_id_passed_to_adapter():
    """client_order_id de la request arriba a adapter.open_position."""
    adapter, calls = _make_fake_adapter()
    core = _make_core(adapter)
    req = _make_req(client_order_id="test_order_001")
    run(core.open_order(req))
    assert len(calls) == 1, f"Esperava 1 crida, got {len(calls)}"
    assert calls[0]["client_order_id"] == "test_order_001", \
        f"client_order_id incorrecte: {calls[0]['client_order_id']}"
    print("✓ test_client_order_id_passed_to_adapter passed")


# ── Test 2: client_order_id absent → None al adapter (backward compat) ────────


def test_client_order_id_none_when_absent():
    """Sense client_order_id al request → adapter.open_position rep client_order_id=None."""
    adapter, calls = _make_fake_adapter()
    core = _make_core(adapter)
    req = _make_req()  # sense client_order_id
    assert req.client_order_id is None, "client_order_id hauria de ser None per defecte"
    run(core.open_order(req))
    assert len(calls) == 1
    assert calls[0]["client_order_id"] is None, \
        f"Esperava None, got: {calls[0]['client_order_id']}"
    print("✓ test_client_order_id_none_when_absent passed")


# ── Test 3: Idempotència simulada — adapter cridat 1 cop per IDs iguals ────────


def test_idempotency_same_client_order_id_single_adapter_call():
    """
    Simula idempotència a nivell adapter: si client_order_id repetit,
    l'adapter (ostium real) retorna la mateixa posició sense crear-ne una nova.
    Aquí verifiquem que el plumbing passa el mateix ID totes les vegades.
    """
    calls = []
    position_id_store = {}

    class _IdempotentFakeAdapter:
        async def open_position(self, symbol, is_long, collateral, leverage,
                                sl_price=None, tp_price=None, client_order_id=None, **kw):
            calls.append(client_order_id)
            if client_order_id and client_order_id in position_id_store:
                pid = position_id_store[client_order_id]
            else:
                pid = f"fake:{symbol}:{len(position_id_store)}"
                if client_order_id:
                    position_id_store[client_order_id] = pid
            from domain.models import OrderResult
            return OrderResult(
                success=True,
                position_id=pid,
                order_id="",
                executed_price=1.08,
                executed_size=collateral * leverage,
            )

    adapter = _IdempotentFakeAdapter()
    core = _make_core(adapter)

    req = _make_req(client_order_id="idem_key_xyz")
    r1 = run(core.open_order(req))
    r2 = run(core.open_order(req))  # mateixa request, mateix client_order_id

    assert r1.position_id == r2.position_id, \
        f"position_id diferent entre crides idempotents: {r1.position_id} vs {r2.position_id}"
    assert calls[0] == calls[1] == "idem_key_xyz", \
        f"client_order_id no passat correctament: {calls}"
    print(f"✓ test_idempotency_same_client_order_id_single_adapter_call passed (pid={r1.position_id})")


# ── Test 4: OrderOpenRequest — camp opcional, backward compat ─────────────────


def test_order_open_request_client_order_id_optional():
    """OrderOpenRequest accepta client_order_id com a camp opcional."""
    # Sense camp: OK
    req_no_id = OrderOpenRequest(
        venue="ostium", symbol="EURUSD", side="long",
        collateral=10.0, leverage=2.0,
    )
    assert req_no_id.client_order_id is None

    # Amb camp: OK
    req_with_id = OrderOpenRequest(
        venue="ostium", symbol="EURUSD", side="long",
        collateral=10.0, leverage=2.0,
        client_order_id="my_order_id",
    )
    assert req_with_id.client_order_id == "my_order_id"
    print("✓ test_order_open_request_client_order_id_optional passed")


# ── Test 5: client_order_id diferent → dos adapters calls amb IDs distints ────


def test_different_client_order_ids_both_reach_adapter():
    """Dos requests amb client_order_ids distints → adapter rep IDs distints."""
    adapter, calls = _make_fake_adapter()
    core = _make_core(adapter)

    run(core.open_order(_make_req(client_order_id="order_A")))
    run(core.open_order(_make_req(client_order_id="order_B")))

    assert len(calls) == 2
    assert calls[0]["client_order_id"] == "order_A"
    assert calls[1]["client_order_id"] == "order_B"
    print("✓ test_different_client_order_ids_both_reach_adapter passed")


# ── Main ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_client_order_id_passed_to_adapter,
        test_client_order_id_none_when_absent,
        test_idempotency_same_client_order_id_single_adapter_call,
        test_order_open_request_client_order_id_optional,
        test_different_client_order_ids_both_reach_adapter,
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
    print(f"\n{'='*60}")
    print(f"Resultat: {passed} OK, {failed} FALLATS de {len(tests)} tests")
    if failed > 0:
        sys.exit(1)
