"""
T5.39 — Test d'import prohibicions (0-network).

Comprova dependències unidireccionals entre capes.

Regles:
1) infrastructure/** NO pot importar application/**
2) apps/realtime_datalayer/** i apps/historical_datalayer/** NO poden importar
   apps/trading_service/** ni application.trading, application.api.broker_routes
3) Cap mòdul fora _archive/ pot importar infrastructure.venues.lighter ni
   infrastructure.venues.gtrade (excepció: testing/helpers/legacy_venue_test_env.py)
"""

import ast
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _collect_imports(file_path: Path) -> list[tuple[str, int]]:
    """Parse file and return [(module_name, line_no), ...] for top-level imports."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (SyntaxError, OSError):
        return []

    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            result.append((mod, node.lineno))
    return result


def _rel_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _module_from_path(path: Path) -> str:
    """Convert path to module name (e.g. infrastructure/paper_market_data/builder.py -> infrastructure.paper_market_data.builder)."""
    rel = _rel_path(path)
    if rel.endswith(".py"):
        rel = rel[:-3]
    elif rel.endswith("/__init__.py"):
        rel = rel[:-12]  # __init__.py
    return rel.replace("/", ".")


def _path_in_archive(path: Path) -> bool:
    rel = _rel_path(path)
    return rel.startswith("_archive/")


def _path_in_excluded(path: Path, excluded: set[str]) -> bool:
    rel = _rel_path(path)
    return any(rel.startswith(ex) for ex in excluded)


def test_rule1_infrastructure_no_import_application():
    """infrastructure/** NO pot importar application/**."""
    violations = []
    infra = ROOT / "infrastructure"
    if not infra.exists():
        return

    for py in infra.rglob("*.py"):
        if _path_in_archive(py):
            continue
        for mod, line in _collect_imports(py):
            if mod.startswith("application.") or mod == "application":
                violations.append((_rel_path(py), line, mod, "infrastructure NO pot importar application"))

    assert not violations, (
        "Regla 1 violada (infrastructure → application):\n"
        + "\n".join(f"  {f}:{ln} import {mod}" for f, ln, mod, _ in violations)
    )


def test_rule2_datalayer_no_import_trading():
    """apps/realtime_datalayer/** i apps/historical_datalayer/** NO poden importar trading_service ni application.trading/broker_routes."""
    violations = []
    forbidden = (
        "apps.trading_service",
        "application.trading",
        "application.api.broker_routes",
    )
    datalayer_dirs = [
        ROOT / "apps" / "realtime_datalayer",
        ROOT / "apps" / "historical_datalayer",
    ]

    for d in datalayer_dirs:
        if not d.exists():
            continue
        for py in d.rglob("*.py"):
            if _path_in_archive(py):
                continue
            for mod, line in _collect_imports(py):
                for prefix in forbidden:
                    if mod == prefix or mod.startswith(prefix + "."):
                        violations.append((_rel_path(py), line, mod, f"datalayer NO pot importar {prefix}"))

    assert not violations, (
        "Regla 2 violada (datalayer → trading):\n"
        + "\n".join(f"  {f}:{ln} import {mod}" for f, ln, mod, _ in violations)
    )


def test_rule3_no_legacy_venue_imports_outside_archive():
    """Cap mòdul fora _archive/ pot importar infrastructure.venues.lighter ni infrastructure.venues.gtrade."""
    violations = []
    legacy_prefixes = ("infrastructure.venues.lighter", "infrastructure.venues.gtrade")
    excluded = {"testing/helpers/legacy_venue_test_env.py"}  # opt-in --include-lighter

    for py in ROOT.rglob("*.py"):
        if _path_in_archive(py):
            continue
        rel = _rel_path(py)
        if _path_in_excluded(py, excluded):
            continue
        for mod, line in _collect_imports(py):
            for prefix in legacy_prefixes:
                if mod.startswith(prefix) or mod == prefix:
                    violations.append((rel, line, mod, "fora _archive NO pot importar venues legacy (lighter/gtrade)"))

    assert not violations, (
        "Regla 3 violada (import legacy fora _archive):\n"
        + "\n".join(f"  {f}:{ln} import {mod}" for f, ln, mod, _ in violations)
    )


def main():
    """Run all boundary tests (per run_all.py)."""
    test_rule1_infrastructure_no_import_application()
    test_rule2_datalayer_no_import_trading()
    test_rule3_no_legacy_venue_imports_outside_archive()


if __name__ == "__main__":
    main()
