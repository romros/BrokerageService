"""
Unit tests: Smoke repeat (M3.5) — --repeat N, fail-fast, log path, SMOKE_RESULT/SMOKE_SUMMARY.

Tests (mock, no network):
- repeat 3 with all OK: run_smoke core called 3 times, SMOKE_RESULT x3, SMOKE_SUMMARY ok=3 failed=0
- run #2 fails: stop immediately, no run #3; exit 1; SMOKE_SUMMARY failed=1
- log file created when --log-path given; content has SMOKE_RESULT and SMOKE_SUMMARY
- default log path when --repeat > 1 and no --log-path: dir datafiles/smoke_runs, file created, SMOKE_SUMMARY contains log_path
"""

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

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


def test_repeat_3_all_ok():
    """--repeat 3 with mock: 3 SMOKE_RESULT lines, SMOKE_SUMMARY ok=3 failed=0."""
    exit_code, out, _ = _capture_main([
        "--venue", "mock", "--mode", "PAPER", "--seconds", "0.05", "--repeat", "3", "--pause-s", "0",
    ])
    assert exit_code == 0
    lines = [l for l in out.splitlines() if l.strip().startswith(smoke_module.SMOKE_RESULT_PREFIX)]
    assert len(lines) == 3, f"Expected 3 SMOKE_RESULT lines, got {len(lines)}: {out}"
    assert "run=1/3" in lines[0] and "run=2/3" in lines[1] and "run=3/3" in lines[2]
    assert all("status=OK" in l and "errors=0" in l for l in lines)
    summary = [l for l in out.splitlines() if l.strip().startswith(smoke_module.SMOKE_SUMMARY_PREFIX)]
    assert len(summary) == 1
    assert "ok=3" in summary[0] and "failed=0" in summary[0]
    print("OK repeat 3 all ok")


def test_repeat_fail_on_second_stops():
    """When run #2 fails, stop immediately; exit 1; no run #3."""
    call_count = [0]

    async def fake_run_smoke(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 2:
            return False, 1
        return True, 0

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("DATAFILES_ROOT")
        try:
            os.environ["DATAFILES_ROOT"] = tmp
            with patch.object(smoke_module, "run_smoke", side_effect=fake_run_smoke):
                exit_code, out, _ = _capture_main([
                    "--venue", "mock", "--seconds", "0.01", "--repeat", "3", "--pause-s", "0",
                ])
        finally:
            if prev is not None:
                os.environ["DATAFILES_ROOT"] = prev
            else:
                os.environ.pop("DATAFILES_ROOT", None)
    assert exit_code == 1
    assert call_count[0] == 2, f"Expected 2 run_smoke calls (stop on fail), got {call_count[0]}"
    result_lines = [l for l in out.splitlines() if l.strip().startswith(smoke_module.SMOKE_RESULT_PREFIX)]
    assert len(result_lines) == 2
    assert "run=1/3" in result_lines[0] and "status=OK" in result_lines[0]
    assert "run=2/3" in result_lines[1] and "status=FAILED" in result_lines[1]
    summary = [l for l in out.splitlines() if l.strip().startswith(smoke_module.SMOKE_SUMMARY_PREFIX)]
    assert len(summary) == 1 and "failed=1" in summary[0]
    print("OK repeat fail on second stops")


def test_log_path_created_and_content():
    """With --log-path, file is created and contains SMOKE_RESULT and SMOKE_SUMMARY."""
    with tempfile.TemporaryDirectory() as tmp:
        log_file = Path(tmp) / "smoke_evidence.log"
        exit_code, out, _ = _capture_main([
            "--venue", "mock", "--seconds", "0.03", "--repeat", "2", "--pause-s", "0",
            "--log-path", str(log_file),
        ])
        assert exit_code == 0
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert smoke_module.SMOKE_RESULT_PREFIX in content
        assert smoke_module.SMOKE_SUMMARY_PREFIX in content
        assert "ok=2" in content and "failed=0" in content
    print("OK log path created and content")


def test_default_log_path_when_repeat_gt_1():
    """With --repeat 2 and no --log-path, default path under datafiles/smoke_runs used and SMOKE_SUMMARY has log_path."""
    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("DATAFILES_ROOT")
        try:
            os.environ["DATAFILES_ROOT"] = tmp
            exit_code, out, _ = _capture_main([
                "--venue", "mock", "--seconds", "0.03", "--repeat", "2", "--pause-s", "0",
            ])
            assert exit_code == 0
            summary = [l for l in out.splitlines() if l.strip().startswith(smoke_module.SMOKE_SUMMARY_PREFIX)]
            assert len(summary) == 1
            assert "log_path=" in summary[0]
            m = re.search(r"log_path=(\S+)", summary[0])
            assert m, summary[0]
            log_path = m.group(1)
            assert "smoke_runs" in log_path
            assert "2x.log" in log_path
            assert Path(log_path).exists() or Path(tmp) in Path(log_path).parents
        finally:
            if prev is not None:
                os.environ["DATAFILES_ROOT"] = prev
            else:
                os.environ.pop("DATAFILES_ROOT", None)
    print("OK default log path when repeat>1")


def main():
    test_repeat_3_all_ok()
    test_repeat_fail_on_second_stops()
    test_log_path_created_and_content()
    test_default_log_path_when_repeat_gt_1()
    print("\nOK All smoke repeat tests passed")


if __name__ == "__main__":
    main()
