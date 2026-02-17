"""
Run all tests

Executes all test scripts in order:
1. Unit tests (store, validator, builder, etc.)
2. Integration tests (backfill flow, etc.)
3. API smoke tests (REST, WebSocket)

P3.2: Default = MVP Lighter (core + Lighter). gTrade tests opt-in amb --include-gtrade.

Returns exit code 0 if all pass, 1 if any fail.
"""


import argparse
import os
from pathlib import Path
import subprocess
import sys

# Project root (run_all.py lives in testing/)
ROOT = Path(__file__).resolve().parent.parent

# P3.2: gTrade-only tests (path-based, excluded per defecte). MVP = Lighter.
GTrade_TEST_PATHS = frozenset({
    "unit/test_gtrade_price_feed_parser.py",
    "unit/test_chain_config.py",
    "unit/test_tx_sender.py",
    "unit/test_position_ref.py",
    "unit/test_abi_encoder.py",
    "unit/test_market_status_provider.py",
    "unit/test_price_provider.py",
    "integration/test_gtrade_ticks_to_candles_flow.py",
    "integration/test_gtrade_adapter_readonly.py",
    "integration/test_gtrade_backend_positions.py",
    "integration/test_gtrade_adapter_write_mocked.py",
    "integration/test_gtrade_backend_verification_loop.py",
    "integration/test_adapter_fallback_flow.py",
})

# P4.0: Lighter backfill (API real, xarxa). Opt-in amb --include-lighter-backfill.
LIGHTER_BACKFILL_TEST_PATHS = frozenset({
    "integration/test_lighter_candles_time_semantics.py",
    "integration/test_lighter_backfill_pagination_dedup.py",
    "integration/test_gap_repair_flow.py",
})

# P4.1: WS vs Candlestick consistency (broker + Lighter real). Opt-in amb --include-consistency.
CONSISTENCY_TEST_PATHS = frozenset({
    "integration/test_ws_vs_candlestick_consistency.py",
})

# P6: compat_probe (primary vs Dukascopy). Opt-in amb --include-compat-probe.
COMPAT_PROBE_TEST_PATHS = frozenset({
    "integration/test_compat_probe_strategy_level.py",
})

# P7c: Data Layer soak (metrics + validation). Opt-in amb --include-data-layer-soak.
DATA_LAYER_SOAK_TEST_PATHS = frozenset({
    "integration/test_data_layer_soak_metrics.py",
})

# P8.1: Compat report real (Lighter vs Dukascopy). Opt-in amb --include-compat-report.
COMPAT_REPORT_TEST_PATHS = frozenset({
    "integration/test_compat_report_real.py",
})

# P4.2: Exit code que els tests opt-in retornen quan fan skip (no fail)
EXIT_SKIP = 2

# Optional: load .env for tests that need Lighter credentials (non-blocking)
try:
    from dotenv import load_dotenv
    env_file = ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass
# Ensure child processes find infrastructure/domain/application
if str(ROOT) not in os.environ.get("PYTHONPATH", "").split(os.pathsep):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
else:
    env = os.environ.copy()


def _is_gtrade_test(test_path: Path, testing_dir: Path) -> bool:
    """True si el test és gTrade-only (exclòs per defecte)."""
    try:
        rel = test_path.resolve().relative_to(testing_dir.resolve())
        return str(rel).replace("\\", "/") in GTrade_TEST_PATHS
    except ValueError:
        return False


def _is_lighter_backfill_test(test_path: Path, testing_dir: Path) -> bool:
    """True si el test requereix Lighter API real (opt-in)."""
    try:
        rel = test_path.resolve().relative_to(testing_dir.resolve())
        return str(rel).replace("\\", "/") in LIGHTER_BACKFILL_TEST_PATHS
    except ValueError:
        return False


def _is_consistency_test(test_path: Path, testing_dir: Path) -> bool:
    """True si el test requereix broker + Lighter real (opt-in)."""
    try:
        rel = test_path.resolve().relative_to(testing_dir.resolve())
        return str(rel).replace("\\", "/") in CONSISTENCY_TEST_PATHS
    except ValueError:
        return False


def _is_compat_probe_test(test_path: Path, testing_dir: Path) -> bool:
    """True si el test requereix compat_probe (primary + Dukascopy, opt-in)."""
    try:
        rel = test_path.resolve().relative_to(testing_dir.resolve())
        return str(rel).replace("\\", "/") in COMPAT_PROBE_TEST_PATHS
    except ValueError:
        return False


def _is_data_layer_soak_test(test_path: Path, testing_dir: Path) -> bool:
    """True si el test requereix Data Layer soak (opt-in)."""
    try:
        rel = test_path.resolve().relative_to(testing_dir.resolve())
        return str(rel).replace("\\", "/") in DATA_LAYER_SOAK_TEST_PATHS
    except ValueError:
        return False


def _is_compat_report_test(test_path: Path, testing_dir: Path) -> bool:
    """True si el test requereix P8.1 compat_report real (opt-in)."""
    try:
        rel = test_path.resolve().relative_to(testing_dir.resolve())
        return str(rel).replace("\\", "/") in COMPAT_REPORT_TEST_PATHS
    except ValueError:
        return False


def run_test(script_path: Path) -> str:
    """
    Run a test script

    Args:
        script_path: Path to test script

    Returns:
        "passed" | "failed" | "skipped"
    """
    print(f"\n{'='*60}")
    print(f"Running: {script_path.name}")
    print('='*60)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(ROOT),
        env=env,
    )

    if result.returncode == 0:
        return "passed"
    if result.returncode == EXIT_SKIP:
        return "skipped"
    return "failed"


def main():
    """Run all tests"""
    parser = argparse.ArgumentParser(
        description="Run BrokerageService test suite. Default: MVP Lighter (core+Lighter).",
    )
    parser.add_argument(
        "--include-gtrade",
        action="store_true",
        help="Include gTrade tests (opt-in; may fail without Arbitrum .env)",
    )
    parser.add_argument(
        "--include-lighter-backfill",
        action="store_true",
        help="Include gap repair flow test (Lighter real API; needs network)",
    )
    parser.add_argument(
        "--include-consistency",
        action="store_true",
        help="Include P4.1 WS vs Candlestick consistency test (broker + Lighter real)",
    )
    parser.add_argument(
        "--include-compat-probe",
        action="store_true",
        help="Include P6 compat_probe (primary vs Dukascopy, 72h overlap)",
    )
    parser.add_argument(
        "--include-data-layer-soak",
        action="store_true",
        help="Include P7c Data Layer soak (metrics + validation, network)",
    )
    parser.add_argument(
        "--include-compat-report",
        action="store_true",
        help="Include P8.1 compat_report real (Lighter vs Dukascopy, network)",
    )
    args = parser.parse_args()

    print("\n" + "="*60)
    print("BrokerageService - Test Suite")
    print("="*60)
    parts = ["core+Lighter"]
    if args.include_gtrade:
        parts.append("gTrade")
    if args.include_lighter_backfill:
        parts.append("lighter-backfill")
    if args.include_consistency:
        parts.append("consistency")
    if args.include_compat_probe:
        parts.append("compat-probe")
    if args.include_data_layer_soak:
        parts.append("data-layer-soak")
    if args.include_compat_report:
        parts.append("compat-report")
    suite_mode = "+".join(parts) or "core+Lighter (MVP)"
    print(f"Suite: {suite_mode}")
    if not args.include_gtrade:
        print("  (gTrade tests excluded; use --include-gtrade to add)")
    if not args.include_lighter_backfill:
        print("  (P4 Lighter backfill tests excluded; use --include-lighter-backfill to add)")
    if not args.include_consistency:
        print("  (P4.1 consistency test excluded; use --include-consistency to add)")
    if not args.include_compat_probe:
        print("  (P6 compat_probe excluded; use --include-compat-probe to add)")
    if not args.include_data_layer_soak:
        print("  (P7c Data Layer soak excluded; use --include-data-layer-soak to add)")
    if not args.include_compat_report:
        print("  (P8.1 compat_report excluded; use --include-compat-report to add)")
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
        testing_dir / "unit" / "test_close_maker_first.py",  # P1.2 maker-first close
        testing_dir / "unit" / "test_smoke_runner.py",  # M3.4 smoke runner + interval
        testing_dir / "unit" / "test_smoke_repeat.py",  # M3.5 smoke --repeat N + log path + SMOKE_RESULT/SUMMARY
        testing_dir / "unit" / "test_smoke_runner_lifecycle.py",  # M3.5.1 lifecycle hardening (start/stop per run)
        testing_dir / "unit" / "test_e2e_trade.py",  # M3.6 Real Paper E2E trading sanity
        testing_dir / "unit" / "test_broker_api.py",  # Broker API
        testing_dir / "unit" / "test_broker_api_trades.py",  # P1 GET /trades
        testing_dir / "unit" / "test_p5_ohlcv_headers_coverage.py",  # P5 Data Observability v0
        testing_dir / "unit" / "test_data_layer_prod_service.py",  # Data Layer prod v0 (prefetch, writer, gates)
        testing_dir / "unit" / "test_data_layer_startup_gate.py",  # Startup gate (0 network)
        testing_dir / "unit" / "test_data_layer_run_eval.py",  # run eval exit codes (0 network)
        testing_dir / "unit" / "test_compose_profiles.py",  # profiles resolen paths, compose config (0 network)
        testing_dir / "unit" / "test_symbol_selection_soak.py",  # P7c.1 select_soak_symbol (0 network)
        testing_dir / "unit" / "test_p7_mixed_gated_stitching.py",  # P7 Mixed gated stitching (0 network)
        testing_dir / "unit" / "test_p8_read_through_response_only.py",  # P8.0 Read-through gap serving (0 network)
        testing_dir / "unit" / "test_compat_registry_parsing.py",  # P7b compat registry robustesa
        testing_dir / "unit" / "test_dukascopy_provider.py",  # P6 Dukascopy provider (cache, parser)
        testing_dir / "unit" / "test_compat_report_service.py",  # P8 Compat report (0 network)
        testing_dir / "unit" / "test_p8_provenance_rest_only.py",  # P8.2 Provenance REST-only (0 network)
        testing_dir / "unit" / "test_ws_collector_persistence.py",  # P8.4 WS Candle Collector persistence (0 network)
        testing_dir / "unit" / "test_trade_history_models.py",  # P1 TradeFill mapping
        testing_dir / "unit" / "test_ws_preflight_contract.py",  # P2.0 WS candle contract
        testing_dir / "unit" / "test_mode_market_data_env.py",  # PAPER mainnet-data (Freqtrade)
        testing_dir / "unit" / "test_paper_venue_adapter.py",  # PaperVenueAdapter open→close→positions_after=0
        testing_dir / "unit" / "test_paper_risk_engine.py",  # P3.0 TP/SL/liquidation triggers

        # Integration tests
        testing_dir / "integration" / "test_live_to_store_flow.py",
        testing_dir / "integration" / "test_backfill_patch_flow.py",
        testing_dir / "integration" / "test_lighter_candles_time_semantics.py",  # P4.0 (opt-in)
        testing_dir / "integration" / "test_lighter_backfill_pagination_dedup.py",  # P4.0 (opt-in)
        testing_dir / "integration" / "test_gap_repair_flow.py",  # P4.0 (opt-in: --include-lighter-backfill)
        testing_dir / "integration" / "test_paper_positions_flow.py",
        testing_dir / "integration" / "test_gtrade_ticks_to_candles_flow.py",
        testing_dir / "integration" / "test_lighter_ticks_to_candles_flow.py",  # M1 Lighter market data
        testing_dir / "integration" / "test_ws_preflight_integration_real.py",  # P2.0.1 WS preflight (fake feed)
        testing_dir / "integration" / "test_ws_soak_short.py",  # P2.1 WS soak short (2 min)
        testing_dir / "integration" / "test_ws_vs_candlestick_consistency.py",  # P4.1 (opt-in: --include-consistency)
        testing_dir / "integration" / "test_compat_probe_strategy_level.py",  # P6 (opt-in: --include-compat-probe)
        testing_dir / "integration" / "test_compat_report_real.py",  # P8.1 (opt-in: --include-compat-report)
        testing_dir / "integration" / "test_data_layer_soak_metrics.py",  # P7c (opt-in: --include-data-layer-soak)
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
        testing_dir / "integration" / "test_freqtrade_runner_short.py",  # PAPER DONE handshake
        testing_dir / "integration" / "test_freqtrade_runner_short_paper.py",  # venue=paper zero tx (no Lighter)
        testing_dir / "integration" / "test_paper_bracket_orders_integration.py",  # P3.0 bracket TP/SL + close_reason

        # API smoke tests
        testing_dir / "api" / "test_rest_smoke.py",
        testing_dir / "api" / "test_p7_mixed_headers_http.py",  # P7b headers via HTTP (0 network)
        testing_dir / "api" / "test_p8_read_through_ohlcv_api.py",  # P8.0b Read-through wired to OHLCV (0 network)
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

        # P3.2: Excloure gTrade per defecte
        if not args.include_gtrade and _is_gtrade_test(test_path, testing_dir):
            print(f"\n⊘ Skipped: {test_path.name} (gTrade; use --include-gtrade)")
            skipped += 1
            continue

        # P4.0: Excloure gap repair flow per defecte (requereix Lighter API real)
        if not args.include_lighter_backfill and _is_lighter_backfill_test(test_path, testing_dir):
            print(f"\n⊘ Skipped: {test_path.name} (Lighter backfill; use --include-lighter-backfill)")
            skipped += 1
            continue

        # P4.1: Excloure consistency test per defecte (requereix broker + Lighter real)
        if not args.include_consistency and _is_consistency_test(test_path, testing_dir):
            print(f"\n⊘ Skipped: {test_path.name} (P4.1 consistency; use --include-consistency)")
            skipped += 1
            continue

        # P6: Excloure compat_probe per defecte (requereix primary + Dukascopy)
        if not args.include_compat_probe and _is_compat_probe_test(test_path, testing_dir):
            print(f"\n⊘ Skipped: {test_path.name} (P6 compat_probe; use --include-compat-probe)")
            skipped += 1
            continue

        # P7c: Excloure Data Layer soak per defecte (requereix Lighter real)
        if not args.include_data_layer_soak and _is_data_layer_soak_test(test_path, testing_dir):
            print(f"\n⊘ Skipped: {test_path.name} (P7c Data Layer soak; use --include-data-layer-soak)")
            skipped += 1
            continue

        # P8.1: Excloure compat_report real per defecte (requereix Lighter + Dukascopy)
        if not args.include_compat_report and _is_compat_report_test(test_path, testing_dir):
            print(f"\n⊘ Skipped: {test_path.name} (P8.1 compat_report; use --include-compat-report)")
            skipped += 1
            continue

        status = run_test(test_path)

        if status == "passed":
            passed += 1
        elif status == "skipped":
            skipped += 1
            print(f"\n⊘ Skipped: {test_path.name} (entorn no preparat)")
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
