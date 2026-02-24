"""
E2E Tests - Real Testnet Transactions

⚠️  MANUAL/SLOW TESTS - NOT RUN IN CI BY DEFAULT

These tests execute REAL blockchain transactions on Arbitrum Sepolia testnet.
They are marked with @pytest.mark.e2e and require explicit opt-in:

Required environment variables:
- E2E_TESTNET=1 (confirms intent to run testnet transactions)
- ENABLE_LIVE_TRADING=1 (enables transaction execution)

Usage:
    # Run all E2E tests
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 pytest testing/e2e/ -v -s

    # Run specific test
    E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 pytest testing/e2e/test_testnet_smoke.py -v -s

Safety:
- Tests verify chain_id == 421614 (Sepolia)
- Abort if mainnet detected
- Collateral limits enforced (MAX_COLLATERAL_USDC)
- Balance checks before execution

CI/CD:
- E2E tests are SKIPPED by default in CI
- Can be enabled via manual pipeline trigger with env vars
"""
