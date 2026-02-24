#!/usr/bin/env python3
"""
Phase G — OstiumExecutionAdapter unit tests (0-network, sense SDK real).

Verifica:
1. open_position OK  → FakeOstiumClient.open_trade cridat, retorna OrderResult(success=True)
2. open_position falla → FakeOstiumClient llança error, retorna OrderResult(success=False)
3. close_position OK → FakeOstiumClient.close_trade cridat, retorna True
4. close_position sense client → VenueAPIError
5. update_sl / update_tp → delegats al client, retornen True
6. get_open_positions → retorna Position[] des de FakeOstiumClient._trades
7. get_open_positions amb FakeOstiumClient sense trades → []
8. health_check True/False → delega al client
9. position_id format → parse i make correctes
10. symbol desconegut → MarketNotFoundError
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.venues.ostium.ostium_client import FakeOstiumClient
from infrastructure.venues.ostium.ostium_execution_adapter import (
    OstiumExecutionAdapter,
    _make_position_id,
    _parse_position_id,
    SYMBOL_TO_PAIR_ID,
)
from domain.errors import MarketNotFoundError, VenueAPIError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fake_adapter(mid_price: float = 1.08500, **kwargs) -> OstiumExecutionAdapter:
    """Crea OstiumExecutionAdapter amb FakeOstiumClient injectat."""
    fake = FakeOstiumClient(mid_price=mid_price, **kwargs)
    adapter = OstiumExecutionAdapter(client=fake)
    return adapter


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_open_position_ok():
    """open_position retorna OrderResult(success=True) i crida el client."""
    adapter = _make_fake_adapter(mid_price=1.085)
    result = run(adapter.open_position(
        symbol="EURUSD",
        is_long=True,
        collateral=100.0,
        leverage=10.0,
    ))
    assert result.success is True
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    assert result.position_id == f"ostium:{pair_id}:0"
    assert result.executed_price == 1.085
    assert result.executed_size == 1000.0  # 100 * 10
    assert result.tx_hash.startswith("0xfake")

    # Verificar que el client va ser cridat
    fake: FakeOstiumClient = adapter._client
    assert len(fake.open_calls) == 1
    call = fake.open_calls[0]
    assert call["pair_id"] == SYMBOL_TO_PAIR_ID["EURUSD"]
    assert call["is_long"] is True
    assert call["collateral"] == 100.0
    assert call["leverage"] == 10


def test_open_position_with_sl_tp():
    """open_position passa sl_price i tp_price al client."""
    adapter = _make_fake_adapter(mid_price=2000.0)
    result = run(adapter.open_position(
        symbol="XAUUSD",
        is_long=True,
        collateral=50.0,
        leverage=5.0,
        sl_price=1950.0,
        tp_price=2100.0,
    ))
    assert result.success is True
    fake: FakeOstiumClient = adapter._client
    call = fake.open_calls[0]
    assert call["sl_price"] == 1950.0
    assert call["tp_price"] == 2100.0


def test_open_position_client_error_returns_failed_result():
    """Si el client llança error, open_position retorna OrderResult(success=False)."""
    adapter = _make_fake_adapter(open_should_fail=True)
    result = run(adapter.open_position(
        symbol="EURUSD",
        is_long=False,
        collateral=50.0,
        leverage=5.0,
    ))
    assert result.success is False
    assert result.position_id == ""
    assert "simulated failure" in result.error_message


def test_open_position_unknown_symbol_raises():
    """Symbol desconegut → MarketNotFoundError."""
    adapter = _make_fake_adapter()
    try:
        run(adapter.open_position(
            symbol="DOESNOTEXIST",
            is_long=True,
            collateral=100.0,
            leverage=2.0,
        ))
        assert False, "Hauria d'haver llançat MarketNotFoundError"
    except MarketNotFoundError:
        pass


def test_open_position_no_client_raises():
    """Adapter sense client inicialitzat → VenueAPIError."""
    adapter = OstiumExecutionAdapter()  # client=None, sense start()
    try:
        run(adapter.open_position("EURUSD", True, 100.0, 2.0))
        assert False, "Hauria d'haver llançat VenueAPIError"
    except VenueAPIError:
        pass


def test_close_position_ok():
    """close_position OK → True i crida close_trade al client."""
    adapter = _make_fake_adapter(mid_price=1.08600)
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]

    # Primer obrim per tenir algo a tancar
    run(adapter.open_position("EURUSD", True, 100.0, 5.0))

    ok = run(adapter.close_position(f"ostium:{pair_id}:0"))
    assert ok is True

    fake: FakeOstiumClient = adapter._client
    assert len(fake.close_calls) == 1
    call = fake.close_calls[0]
    assert call["pair_id"] == pair_id
    assert call["trade_index"] == 0
    assert call["at_price"] == 1.08600


def test_close_position_client_error_returns_false():
    """Si close_trade falla, close_position retorna False."""
    adapter = _make_fake_adapter(close_should_fail=True)
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    # Obrir un trade primer (idempotència: si no existeix → True sense cridar SDK)
    run(adapter.open_position("EURUSD", True, 100.0, 5.0))
    # Ara el trade existeix → el check idempotent passa (collateral>0), i close_trade falla
    ok = run(adapter.close_position(f"ostium:{pair_id}:0"))
    assert ok is False


def test_close_position_no_client_raises():
    """Adapter sense client → VenueAPIError."""
    adapter = OstiumExecutionAdapter()
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    try:
        run(adapter.close_position(f"ostium:{pair_id}:0"))
        assert False
    except VenueAPIError:
        pass


def test_close_position_invalid_format_raises():
    """Position ID amb format invàlid → VenueAPIError."""
    adapter = _make_fake_adapter()
    try:
        run(adapter.close_position("ostium:only_one_part"))
        assert False
    except VenueAPIError as e:
        assert "invàlid" in str(e).lower() or "invalid" in str(e).lower() or "parsejar" in str(e).lower()


def test_update_sl_delegates_to_client():
    """update_sl → IOstiumClient.update_sl cridada."""
    adapter = _make_fake_adapter()
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    run(adapter.open_position("EURUSD", True, 100.0, 5.0))
    ok = run(adapter.update_sl(f"ostium:{pair_id}:0", new_sl=1.07000))
    assert ok is True
    fake: FakeOstiumClient = adapter._client
    assert len(fake.sl_calls) == 1
    assert fake.sl_calls[0]["new_sl"] == 1.07000
    assert fake.sl_calls[0]["pair_id"] == pair_id
    assert fake.sl_calls[0]["trade_index"] == 0


def test_update_tp_delegates_to_client():
    """update_tp → IOstiumClient.update_tp cridada."""
    adapter = _make_fake_adapter()
    ok = run(adapter.update_tp("ostium:1:2", new_tp=2100.0))
    assert ok is True
    fake: FakeOstiumClient = adapter._client
    assert len(fake.tp_calls) == 1
    assert fake.tp_calls[0]["pair_id"] == 1
    assert fake.tp_calls[0]["trade_index"] == 2
    assert fake.tp_calls[0]["new_tp"] == 2100.0


def test_get_open_positions_returns_positions():
    """get_open_positions retorna posicions obertes des del FakeOstiumClient."""
    adapter = _make_fake_adapter(mid_price=1.085)

    # Obrir dos trades
    run(adapter.open_position("EURUSD", True, 100.0, 5.0))
    run(adapter.open_position("EURUSD", False, 50.0, 3.0))

    # Simular trader_address (FakeOstiumClient no en té però l'adapter la busca per getattr)
    adapter._client._trader_address = "0xFakeTrader"

    positions = run(adapter.get_open_positions())
    assert len(positions) == 2
    assert all(p.symbol == "EURUSD" for p in positions)
    assert any(p.is_long for p in positions)
    assert any(not p.is_long for p in positions)
    # Verificar format position_id (pair_id = SYMBOL_TO_PAIR_ID["EURUSD"])
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    pids = {p.venue_position_id for p in positions}
    assert f"ostium:{pair_id}:0" in pids
    assert f"ostium:{pair_id}:1" in pids


def test_get_open_positions_no_trader_address_returns_empty():
    """Si trader_address no disponible, get_open_positions retorna []."""
    adapter = _make_fake_adapter()
    # FakeOstiumClient no té _trader_address per defecte → []
    positions = run(adapter.get_open_positions())
    assert positions == []


def test_get_open_positions_no_client_returns_empty():
    """Adapter sense client → []."""
    adapter = OstiumExecutionAdapter()
    positions = run(adapter.get_open_positions())
    assert positions == []


def test_health_check_true():
    """health_check retorna True si el client health() retorna True."""
    adapter = _make_fake_adapter(health_result=True)
    ok = run(adapter.health_check())
    assert ok is True


def test_health_check_false():
    """health_check retorna False si el client health() retorna False."""
    adapter = _make_fake_adapter(health_result=False)
    ok = run(adapter.health_check())
    assert ok is False


def test_health_check_no_client_returns_false():
    """health_check sense client → False."""
    adapter = OstiumExecutionAdapter()
    ok = run(adapter.health_check())
    assert ok is False


def test_position_id_format():
    """_make_position_id i _parse_position_id coherents."""
    pid = _make_position_id(pair_id=3, trade_index=7)
    assert pid == "ostium:3:7"
    pair_id, trade_index = _parse_position_id(pid)
    assert pair_id == 3
    assert trade_index == 7

    # Amb prefix "ostium:"
    pair_id2, trade_index2 = _parse_position_id("ostium:5:12")
    assert pair_id2 == 5
    assert trade_index2 == 12


def test_venue_properties():
    """venue_name, is_live, is_paper, is_backtest, get_mode."""
    adapter = OstiumExecutionAdapter()
    assert adapter.venue_name == "ostium"
    assert adapter.is_live is True
    assert adapter.is_paper is False
    assert adapter.is_backtest is False
    assert adapter.get_mode() == "live"


def test_get_trade_history_returns_empty():
    """get_trade_history retorna [] (subgraph no disponible)."""
    adapter = _make_fake_adapter()
    fills = run(adapter.get_trade_history())
    assert fills == []


def test_get_pairs_returns_empty():
    """get_pairs retorna [] (subgraph no disponible)."""
    adapter = _make_fake_adapter()
    pairs = run(adapter.get_pairs())
    assert pairs == []


def test_start_no_env_key_adapter_inactiu():
    """start() sense OSTIUM_PRIVATE_KEY → adapter inactiu (client=None), no error."""
    import os
    old_key = os.environ.pop("OSTIUM_PRIVATE_KEY", None)
    try:
        adapter = OstiumExecutionAdapter()
        run(adapter.start())
        assert adapter._client is None  # inactiu, no error
    finally:
        if old_key:
            os.environ["OSTIUM_PRIVATE_KEY"] = old_key


def test_short_position_ok():
    """open_position SHORT funciona correctament."""
    adapter = _make_fake_adapter(mid_price=1.085)
    result = run(adapter.open_position(
        symbol="EURUSD",
        is_long=False,
        collateral=200.0,
        leverage=20.0,
    ))
    assert result.success is True
    fake: FakeOstiumClient = adapter._client
    assert fake.open_calls[0]["is_long"] is False


# ── Phase H: tests nous ────────────────────────────────────────────────────────


def test_close_position_idempotent_already_closed():
    """close_position sobre trade ja tancat → True sense cridar close_trade."""
    adapter = _make_fake_adapter()
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    # FakeOstiumClient buit (cap trade) → get_trade_info retorna None → idempotent
    ok = run(adapter.close_position(f"ostium:{pair_id}:0"))
    assert ok is True
    fake: FakeOstiumClient = adapter._client
    assert len(fake.close_calls) == 0, "close_trade no hauria de ser cridat si ja tancat"
    print("✓ test_close_position_idempotent_already_closed passed")


def test_get_balance_returns_balance():
    """get_balance: usdc, used_margin (collateral posicions), available_margin."""
    fake = FakeOstiumClient(mid_price=1.085, usdc_balance=200.0)
    adapter = OstiumExecutionAdapter(client=fake)
    fake._trader_address = "0xFakeTrader"

    # Obrir posició amb collateral=50
    run(adapter.open_position("EURUSD", True, 50.0, 5.0))

    balance = run(adapter.get_balance())
    assert balance.usdc == 200.0
    assert balance.used_margin == 50.0
    assert balance.available_margin == 150.0
    print("✓ test_get_balance_returns_balance passed")


def test_get_position_metrics_long_profit():
    """get_position_metrics LONG: si preu puja, pnl positiu (fórmula manual)."""
    open_price = 1.08000
    current_price = 1.09000  # +0.926%
    fake = FakeOstiumClient(mid_price=open_price)
    adapter = OstiumExecutionAdapter(client=fake)
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]

    # Obrir posició (open_price=1.08, collateral=100, leverage=10, notional=1000)
    run(adapter.open_position("EURUSD", True, 100.0, 10.0))

    # Canviar preu del fake per simular profit
    fake.mid_price = current_price

    metrics = run(adapter.get_position_metrics(f"ostium:{pair_id}:0"))
    assert metrics.unrealized_pnl > 0, f"PnL hauria de ser positiu, got {metrics.unrealized_pnl}"
    assert metrics.unrealized_pnl_percent > 0
    assert metrics.current_price == current_price
    # Liquidation price LONG: open * (1 - 1/leverage) = 1.08 * 0.9 = 0.972
    assert abs(metrics.liquidation_price - (open_price * 0.9)) < 0.001
    print(f"✓ test_get_position_metrics_long_profit passed "
          f"(PnL={metrics.unrealized_pnl:.4f} liq={metrics.liquidation_price:.5f})")


def test_get_position_metrics_not_found():
    """get_position_metrics sobre trade inexistent → VenueAPIError."""
    adapter = _make_fake_adapter()
    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    try:
        run(adapter.get_position_metrics(f"ostium:{pair_id}:99"))
        assert False, "Hauria d'haver llançat VenueAPIError"
    except VenueAPIError as e:
        assert (
            "no trobat" in str(e).lower()
            or "tancat" in str(e).lower()
            or "collateral" in str(e).lower()
        )
    print("✓ test_get_position_metrics_not_found passed")


def test_open_position_idempotent_disc(tmp_path=None):
    """Dues crides open amb same client_order_id → 2a retorna same position_id, 1 sola crida al client."""
    import tempfile
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
        idem_file = str(Path(tmp_path) / "trade_ids.jsonl")
    else:
        idem_file = str(tmp_path / "trade_ids.jsonl")

    fake = FakeOstiumClient(mid_price=1.085)
    adapter = OstiumExecutionAdapter(client=fake, _idempotency_file=idem_file)

    pair_id = SYMBOL_TO_PAIR_ID["EURUSD"]
    # Primera crida
    r1 = run(adapter.open_position(
        symbol="EURUSD", is_long=True, collateral=100.0, leverage=5.0,
        client_order_id="order-abc-123",
    ))
    assert r1.success is True
    assert r1.position_id == f"ostium:{pair_id}:0"
    assert len(fake.open_calls) == 1

    # Segona crida — mateixa client_order_id
    r2 = run(adapter.open_position(
        symbol="EURUSD", is_long=True, collateral=100.0, leverage=5.0,
        client_order_id="order-abc-123",
    ))
    assert r2.success is True
    assert r2.position_id == r1.position_id, "Ha de retornar el same position_id"
    assert len(fake.open_calls) == 1, "No hauria de cridar open_trade una 2a vegada"
    print("✓ test_open_position_idempotent_disc passed")


if __name__ == "__main__":
    tests = [
        test_open_position_ok,
        test_open_position_with_sl_tp,
        test_open_position_client_error_returns_failed_result,
        test_open_position_unknown_symbol_raises,
        test_open_position_no_client_raises,
        test_close_position_ok,
        test_close_position_client_error_returns_false,
        test_close_position_no_client_raises,
        test_close_position_invalid_format_raises,
        test_update_sl_delegates_to_client,
        test_update_tp_delegates_to_client,
        test_get_open_positions_returns_positions,
        test_get_open_positions_no_trader_address_returns_empty,
        test_get_open_positions_no_client_returns_empty,
        test_health_check_true,
        test_health_check_false,
        test_health_check_no_client_returns_false,
        test_position_id_format,
        test_venue_properties,
        test_get_trade_history_returns_empty,
        test_get_pairs_returns_empty,
        test_start_no_env_key_adapter_inactiu,
        test_short_position_ok,
        # Phase H
        test_close_position_idempotent_already_closed,
        test_get_balance_returns_balance,
        test_get_position_metrics_long_profit,
        test_get_position_metrics_not_found,
        test_open_position_idempotent_disc,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
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
