"""
Run all tests

Executes all test scripts in order:
1. Unit tests (store, validator, builder, etc.)
2. Integration tests (backfill flow, etc.)
3. API smoke tests (REST, WebSocket)

Returns exit code 0 if all pass, 1 if any fail.
"""


from pathlib import Path
import subprocess
import sys


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
        cwd=script_path.parent.parent.parent,  # Project root
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
        # Unit tests
        testing_dir / "unit" / "test_candle_store.py",
        testing_dir / "unit" / "test_gap_validator.py",
        testing_dir / "unit" / "test_candle_builder.py",
        testing_dir / "unit" / "test_backfill_provider.py",
        testing_dir / "unit" / "test_idempotency.py",
        testing_dir / "unit" / "test_cost_model.py",
        testing_dir / "unit" / "test_gtrade_price_feed_parser.py",
        testing_dir / "unit" / "test_chain_config.py",
        testing_dir / "unit" / "test_tx_sender.py",
        testing_dir / "unit" / "test_position_ref.py",
        testing_dir / "unit" / "test_abi_encoder.py",
        testing_dir / "unit" / "test_market_status_provider.py",  # FASE 6B.1.B.6
        testing_dir / "unit" / "test_price_provider.py",  # FASE 6B.1.B.7.LAB

        # Integration tests
        testing_dir / "integration" / "test_live_to_store_flow.py",
        testing_dir / "integration" / "test_backfill_patch_flow.py",
        testing_dir / "integration" / "test_paper_positions_flow.py",
        testing_dir / "integration" / "test_gtrade_ticks_to_candles_flow.py",
        testing_dir / "integration" / "test_gtrade_adapter_readonly.py",
        testing_dir / "integration" / "test_gtrade_backend_positions.py",
        testing_dir / "integration" / "test_gtrade_adapter_write_mocked.py",
        testing_dir / "integration" / "test_gtrade_backend_verification_loop.py",  # FASE 6B.1.B.4
        testing_dir / "integration" / "test_adapter_fallback_flow.py",  # FASE 6B.1.B.6

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
