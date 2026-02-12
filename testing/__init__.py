"""
Testing - Simple Python test scripts (no pytest)

Philosophy:
- Each script is standalone with main()
- Uses plain asserts
- Prints results to stdout
- Returns exit code 0 (pass) or 1 (fail)
- run_all.py executes all tests

Structure:
- unit/: Test pure classes (store, validator, builder)
- integration/: Test component interactions (backfill flow, etc.)
- api/: Smoke tests for REST endpoints
"""
