# Testing - BrokerageService

Simple Python test scripts (no pytest framework).

## Philosophy

- **Simple**: Each test is a standalone Python script with `main()`
- **Clear**: Uses plain `assert` statements
- **Visible**: Prints results to stdout
- **Exit codes**: Returns 0 (pass) or 1 (fail)
- **No dependencies**: No pytest, just standard library + project code

## Structure

```
testing/
├── unit/               # Unit tests (pure classes)
│   ├── test_candle_store.py
│   ├── test_gap_validator.py
│   └── test_candle_builder.py  (future)
│
├── integration/        # Integration tests (component interactions)
│   ├── test_backfill_patch_flow.py  (future)
│   └── test_live_to_store_flow.py   (future)
│
├── api/                # API smoke tests
│   ├── test_rest_smoke.py
│   └── test_ws_smoke.py  (future)
│
├── run_all.py          # Run all tests
└── README.md           # This file
```

## Running Tests

### Run all tests

```bash
python testing/run_all.py
```

### Run specific test

```bash
python testing/unit/test_candle_store.py
python testing/unit/test_gap_validator.py
python testing/api/test_rest_smoke.py
```

## Test Requirements

### Unit tests
- No external dependencies
- Run in isolation (temp directories)
- Fast (<1s per test)

### Integration tests
- May require storage/files
- Test component interactions
- Medium speed (1-5s)

### API smoke tests
- Require server to be running (or start it)
- Test actual HTTP endpoints
- Slower (5-10s)

## Writing Tests

### Template

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import project code
from domain.models import Candle

def test_something():
    """Test description"""
    print("Testing something...")

    # Test code
    result = do_something()

    # Assert
    assert result == expected, f"Expected {expected}, got {result}"

    print("✓ Test passed")

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Test Suite Name")
    print("="*60 + "\n")

    try:
        test_something()
        # ... more tests

        print("\n" + "="*60)
        print("✓ All tests passed!")
        print("="*60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

## CI/CD Integration

To use in CI pipelines:

```bash
cd /path/to/BrokerageService
python testing/run_all.py
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "Tests failed!"
    exit 1
fi
```

## Current Coverage

### ✅ Implemented (Fase 1)
- `test_candle_store.py` - CSV storage operations
- `test_gap_validator.py` - Gap detection and validation
- `test_rest_smoke.py` - REST API endpoints (/health, /mode, /ohlcv)

### 📋 TODO (Future Phases)
- `test_candle_builder.py` - Tick aggregation
- `test_backfill_patch_flow.py` - Backfill scheduler
- `test_live_to_store_flow.py` - Live ingestion
- `test_ws_smoke.py` - WebSocket channels
- `test_idempotency.py` - Trading idempotency
- `test_reconcile_positions.py` - Position reconciliation

## Notes

- Tests use temporary directories (auto-cleanup)
- API tests start their own server on port 8001
- All tests are timezone-aware (America/New_York)
- No test should take >30 seconds
