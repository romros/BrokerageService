import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_august_job_failure_is_not_reported_as_empty_coverage_success(tmp_path):
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *'/sync/fakejob'*) printf '%s' '{\"status\":\"FAILED\",\"failed_months\":[\"2026-08\"]}' ;;\n"
        "  *'/sync'*) printf '%s' '{\"job_id\":\"fakejob\",\"status\":\"RUNNING\",\"is_new\":true}' ;;\n"
        "  *) printf '%s' '{\"months_done\":0,\"months_missing\":[],\"total_rows\":0}' ;;\n"
        "esac\n"
    )
    fake_curl.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    result = subprocess.run(
        [str(ROOT / "scripts/sync_symbol.sh"), "GBPUSD",
         "--from", "2026-08-01", "--to", "2026-08-31",
         "--max-retries", "0", "--poll-interval", "1"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "SyntaxError" not in output
    assert "Coverage OK" not in output
    assert "sincronització ha fallat" in output
