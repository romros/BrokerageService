"""
Run all tests

Executes all test scripts in order:
1. Unit tests (store, validator, builder, etc.)
2. Integration tests (backfill flow, etc.)
3. API smoke tests (REST, WebSocket)

Returns exit code 0 if all pass, 1 if any fail.
"""


import os
from pathlib import Path
import subprocess
import sys

# Project root (run_all.py lives in testing/)
ROOT = Path(__file__).resolve().parent.parent
# Ensure child processes find infrastructure/domain/application
if str(ROOT) not in os.environ.get("PYTHONPATH", "").split(os.pathsep):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
else:
    env = os.environ.copy()


def run_test(script_path: Path) -> bool:
    """
    Run a test script

    Args:
        script_path: Path to test script

    Returns:
        True if test passed (exit code 0), False otherwise
    """
    print(f"\n{'='*60}")
    print(f"Running: {script_path.name}")
    print('='*60)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(ROOT),
        env=env,
    )

    return result.returncode == 0


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("BrokerageService - Test Suite")
    print("="*60)

    testing_dir = Path(__file__).parent

    # Define test order
    tests = [
        # Unit tests - Core
        testing_dir / "unit" / "test_candle_store.py",
        testing_dir / "unit" / "test_candle_semantics.py",  # AGENTS §5.1 interval [ts, ts+60)
        testing_dir / "unit" / "test_gap_validator.py",
        testing_dir / "unit" / "test_candle_builder.py",
        testing_dir / "unit" / "test_backfill_provider.py",
        testing_dir / "unit" / "test_idempotency.py",
        testing_dir / "unit" / "test_cost_model.py",

        # Unit tests - gTrade
        testing_dir / "unit" / "test_gtrade_price_feed_parser.py",
        testing_dir / "unit" / "test_chain_config.py",
        testing_dir / "unit" / "test_tx_sender.py",
        testing_dir / "unit" / "test_position_ref.py",
        testing_dir / "unit" / "test_abi_encoder.py",
        testing_dir / "unit" / "test_market_status_provider.py",  # FASE 6B.1.B.6
        testing_dir / "unit" / "test_price_provider.py",  # FASE 6B.1.B.7.LAB

        # Unit tests - Lighter (TASK 2 - L0/L1)
        testing_dir / "unit" / "test_lighter_key_manager.py",
        testing_dir / "unit" / "test_lighter_scaling.py",
        testing_dir / "unit" / "test_lighter_order_builder.py",
        testing_dir / "unit" / "test_lighter_idempotency.py",
        testing_dir / "unit" / "test_reconcile_service.py",  # M3 Reconcile loop (detect/report)
        testing_dir / "unit" / "test_reconcile_autorepair.py",  # M3.1 auto-repair v1 (stale + resync)
        testing_dir / "unit" / "test_live_guards.py",  # M3.2 kill switch + risk limits
        testing_dir / "unit" / "test_bootstrap_service.py",  # M3.3a bootstrap tracker
        testing_dir / "unit" / "test_sltp_persistence.py",
        testing_dir / "unit" / "test_sltp_idempotency.py",  # P1.1 SL/TP idempotency  # M3.3b SL/TP persistence
        testing_dir / "unit" / "test_smoke_runner.py",  # M3.4 smoke runner + interval
        testing_dir / "unit" / "test_smoke_repeat.py",  # M3.5 smoke --repeat N + log path + SMOKE_RESULT/SUMMARY
        testing_dir / "unit" / "test_smoke_runner_lifecycle.py",  # M3.5.1 lifecycle hardening (start/stop per run)
        testing_dir / "unit" / "test_e2e_trade.py",  # M3.6 Real Paper E2E trading sanity
        testing_dir / "unit" / "test_broker_api.py",  # Broker API
        testing_dir / "unit" / "test_broker_api_trades.py",  # P1 GET /trades
        testing_dir / "unit" / "test_trade_history_models.py",  # P1 TradeFill mapping
        testing_dir / "unit" / "test_ws_preflight_contract.py",  # P2.0 WS candle contract
        testing_dir / "unit" / "test_mode_market_data_env.py",  # PAPER mainnet-data (Freqtrade)

        # Integration tests
        testing_dir / "integration" / "test_live_to_store_flow.py",
        testing_dir / "integration" / "test_backfill_patch_flow.py",
        testing_dir / "integration" / "test_paper_positions_flow.py",
        testing_dir / "integration" / "test_gtrade_ticks_to_candles_flow.py",
        testing_dir / "integration" / "test_lighter_ticks_to_candles_flow.py",  # M1 Lighter market data
        testing_dir / "integration" / "test_ws_preflight_integration_real.py",  # P2.0.1 WS preflight (fake feed)
        testing_dir / "integration" / "test_ws_soak_short.py",  # P2.1 WS soak short (2 min)
        testing_dir / "integration" / "test_gtrade_adapter_readonly.py",
        testing_dir / "integration" / "test_gtrade_backend_positions.py",
        testing_dir / "integration" / "test_gtrade_adapter_write_mocked.py",
        testing_dir / "integration" / "test_gtrade_backend_verification_loop.py",  # FASE 6B.1.B.4
        testing_dir / "integration" / "test_adapter_fallback_flow.py",  # FASE 6B.1.B.6

        # Integration tests - Lighter (TASK 3 - L2 Market Data, TASK 4A - Open Position)
        testing_dir / "integration" / "test_lighter_adapter_prices.py",
        testing_dir / "integration" / "test_lighter_adapter_open.py",
        testing_dir / "integration" / "test_lighter_adapter_close.py",
        testing_dir / "integration" / "test_lighter_adapter_sltp.py",  # M2 SL/TP + Balance

        # API smoke tests
        testing_dir / "api" / "test_rest_smoke.py",
        testing_dir / "api" / "test_ws_smoke.py",
    ]

    # Run tests
    passed = 0
    failed = 0
    skipped = 0

    for test_path in tests:
        if not test_path.exists():
            print(f"\n⊘ Skipped: {test_path.name} (not found)")
            skipped += 1
            continue

        success = run_test(test_path)

        if success:
            passed += 1
        else:
            failed += 1
            print(f"\n✗ FAILED: {test_path.name}")

    # Summary
    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)
    print(f"  Passed:  {passed}")
    print(f"  Failed:  {failed}")
    print(f"  Skipped: {skipped}")
    print("="*60)

    if failed > 0:
        print("\n✗ Some tests failed")
        return 1
    else:
        print("\n✓ All tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
