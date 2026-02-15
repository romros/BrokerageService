"""
Helper per arrencar broker subprocess amb captura de logs (P3.1 diagnostics).

Redirigeix stdout/stderr a fitxer per evitar bloqueig per buffer PIPE ple.
En cas de timeout o fallada: imprimeix últimes N línies i path del log.

Ús:
    broker_log_path, process = start_broker_with_logs(cmd, env, cwd, log_dir)
    # ... run test ...
    if failed:
        dump_broker_log_on_failure(broker_log_path, last_n=300)
"""

from pathlib import Path
import subprocess
from typing import Optional

BROKER_LOG_LAST_N = 300  # Últimes línies a imprimir en fallada


def start_broker_with_logs(
    cmd: list[str],
    env: dict,
    cwd: str,
    log_dir: Path,
    port: int = 0,
) -> tuple[Path, subprocess.Popen]:
    """
    Arrenca broker subprocess amb stdout/stderr redirigits a fitxer.

    Evita bloqueig per buffer PIPE ple (64KB) que faria el broker mut.

    Returns:
        (log_path, process)
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / (f"broker_{port}.log" if port else "broker.log")
    log_file = open(log_path, "w", encoding="utf-8")

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return log_path, process


def dump_broker_log_on_failure(log_path: Optional[Path], last_n: int = BROKER_LOG_LAST_N) -> None:
    """
    Imprimeix últimes N línies del log del broker quan el test falla.

    Crida-ho des del test en cas de timeout, assert, o exit_code != 0.
    """
    if log_path is None or not log_path.exists():
        print(f"\n[Broker log not found: {log_path}]")
        return

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        print(f"\n[Could not read broker log: {e}]")
        return

    n = min(last_n, len(lines))
    excerpt = lines[-n:] if n else []

    print("\n" + "=" * 60)
    print("BROKER LOG (last {} lines) — saved at: {}".format(n, log_path))
    print("=" * 60)
    for line in excerpt:
        print(line)
    print("=" * 60 + "\n")
