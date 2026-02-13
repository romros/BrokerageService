"""
Unit tests: Smoke runner lifecycle (M3.5.1) — adapter start/stop per run, cleanup robust.

Tests (mock):
- repeat 3: adapter.start() and adapter.stop() called 3 times (1 per run)
- adapter.stop() called even if run fails (try/finally)
- no resource leaks (sessions closed)
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application import smoke as smoke_module


def _capture_main(argv):
    """Run smoke.main() with given argv; return (exit_code, stdout_str, stderr_str)."""
    from io import StringIO
    old_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.argv = ["smoke"] + argv
        out = StringIO()
        err = StringIO()
        sys.stdout = out
        sys.stderr = err
        exit_code = smoke_module.main()
        return exit_code, out.getvalue(), err.getvalue()
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def test_lighter_start_stop_called_per_run():
    """--venue lighter --repeat 3: adapter.start() and stop() called 3 times each (1 per run)."""
    import tempfile
    import os

    # Mock adapter with start/stop
    mock_adapter = AsyncMock()
    mock_adapter.start = AsyncMock()
    mock_adapter.stop = AsyncMock()
    mock_adapter.get_open_positions = AsyncMock(return_value=[])

    # Mock tracker
    mock_tracker = type("MockTracker", (), {"get_positions": lambda self: []})()

    # Mock run_bootstrap
    async def mock_bootstrap(adapter, tracker):
        pass

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("DATAFILES_ROOT")
        try:
            os.environ["DATAFILES_ROOT"] = tmp
            with patch("infrastructure.builders.lighter_di.build_lighter_paper_adapter", return_value=mock_adapter):
                with patch("infrastructure.reconcile.InMemoryPositionTracker", return_value=mock_tracker):
                    with patch("application.smoke.run_bootstrap", side_effect=mock_bootstrap):
                        exit_code, out, _ = _capture_main([
                            "--venue", "lighter", "--seconds", "0.05", "--repeat", "3", "--pause-s", "0",
                        ])
        finally:
            if prev is not None:
                os.environ["DATAFILES_ROOT"] = prev
            else:
                os.environ.pop("DATAFILES_ROOT", None)

    assert exit_code == 0
    # start() and stop() should be called 3 times (once per run)
    assert mock_adapter.start.call_count == 3, f"Expected 3 start() calls, got {mock_adapter.start.call_count}"
    assert mock_adapter.stop.call_count == 3, f"Expected 3 stop() calls, got {mock_adapter.stop.call_count}"
    print("OK lighter start/stop called per run (3x)")


def test_lighter_stop_called_even_on_bootstrap_failure():
    """If bootstrap fails, adapter.stop() still called (try/finally)."""
    import tempfile
    import os

    mock_adapter = AsyncMock()
    mock_adapter.start = AsyncMock()
    mock_adapter.stop = AsyncMock()
    mock_adapter.get_open_positions = AsyncMock(return_value=[])

    mock_tracker = type("MockTracker", (), {"get_positions": lambda self: []})()

    async def failing_bootstrap(adapter, tracker):
        raise RuntimeError("bootstrap failed")

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("DATAFILES_ROOT")
        try:
            os.environ["DATAFILES_ROOT"] = tmp
            with patch("infrastructure.builders.lighter_di.build_lighter_paper_adapter", return_value=mock_adapter):
                with patch("infrastructure.reconcile.InMemoryPositionTracker", return_value=mock_tracker):
                    with patch("application.smoke.run_bootstrap", side_effect=failing_bootstrap):
                        exit_code, out, _ = _capture_main([
                            "--venue", "lighter", "--seconds", "0.05", "--repeat", "1", "--pause-s", "0",
                        ])
        finally:
            if prev is not None:
                os.environ["DATAFILES_ROOT"] = prev
            else:
                os.environ.pop("DATAFILES_ROOT", None)

    assert exit_code == 1  # failed
    # start() called once
    assert mock_adapter.start.call_count == 1
    # stop() called even though bootstrap failed (try/finally)
    assert mock_adapter.stop.call_count == 1, f"Expected stop() to be called even on failure, got {mock_adapter.stop.call_count}"
    print("OK lighter stop() called even on bootstrap failure (try/finally)")


def test_lighter_stop_called_even_with_tick_errors():
    """Even if reconcile tick has errors, adapter.stop() is called (cleanup guaranteed)."""
    import tempfile
    import os

    mock_adapter = AsyncMock()
    mock_adapter.start = AsyncMock()
    mock_adapter.stop = AsyncMock()
    # Simulate tick errors (handled by on_tick_error, not critical)
    mock_adapter.get_open_positions = AsyncMock(side_effect=[[], RuntimeError("tick error")])

    mock_tracker = type("MockTracker", (), {"get_positions": lambda self: []})()

    async def mock_bootstrap(adapter, tracker):
        pass

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("DATAFILES_ROOT")
        try:
            os.environ["DATAFILES_ROOT"] = tmp
            with patch("infrastructure.builders.lighter_di.build_lighter_paper_adapter", return_value=mock_adapter):
                with patch("infrastructure.reconcile.InMemoryPositionTracker", return_value=mock_tracker):
                    with patch("application.smoke.run_bootstrap", side_effect=mock_bootstrap):
                        exit_code, out, _ = _capture_main([
                            "--venue", "lighter", "--seconds", "0.05", "--repeat", "1", "--pause-s", "0",
                        ])
        finally:
            if prev is not None:
                os.environ["DATAFILES_ROOT"] = prev
            else:
                os.environ.pop("DATAFILES_ROOT", None)

    # Tick errors handled by on_tick_error are not critical (exit code can be 0 or 1 depending on error_count threshold)
    # Main goal: stop() called even with errors
    assert mock_adapter.start.call_count == 1
    assert mock_adapter.stop.call_count == 1, f"Expected stop() to be called even with tick errors, got {mock_adapter.stop.call_count}"
    print("OK lighter stop() called even with tick errors (cleanup guaranteed)")


def main():
    test_lighter_start_stop_called_per_run()
    test_lighter_stop_called_even_on_bootstrap_failure()
    test_lighter_stop_called_even_with_tick_errors()
    print("\nOK All smoke runner lifecycle tests passed")


if __name__ == "__main__":
    main()
