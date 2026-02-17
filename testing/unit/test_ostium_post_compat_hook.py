#!/usr/bin/env python3
"""
Ostium post-compat hook — unit tests (0-network)

Case A: no candles al store → post-compat SKIP, no registry write.
Case B: candles fixture + dukascopy fixture (candles_b_override) → registry updated, allowed segons verdict.
"""

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from application.tools.ostium_compat_report import run_compat
from application.tools.data_layer_soak import _run_post_compat
from infrastructure.storage.csv_store import CSVCandleStore


def _candle(symbol: str, base: datetime, offset_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol, base + timedelta(minutes=offset_min), o, h, l, c, 0)


def test_post_compat_skip_when_no_candles():
    """Case A: store buit → SKIP, no registry write."""
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp) / "datafiles")
        Path(root).mkdir(parents=True, exist_ok=True)
        result = _run_post_compat(
            compat_symbol="EURUSD",
            compat_candles=650,
            datafiles_root=root,
            broker="gtrade",
        )
        assert result.get("skipped") is True
        assert result.get("verdict") == "SKIP"
        assert result.get("ostium_primary_allowed") is False
        registry_path = Path(root) / "compat_reports" / "ostium_compat_registry.json"
        assert not registry_path.exists()
        print("✓ post-compat SKIP when no candles OK")


def test_post_compat_registry_updated_with_fixtures():
    """Case B: candles al store + dukascopy fixture → registry updated, verdict reflectat."""
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp) / "datafiles")
        Path(root).mkdir(parents=True, exist_ok=True)
        store = CSVCandleStore(root_path=root, broker="gtrade", canonical_tz="America/New_York")

        # Base dins la finestra que run_compat usa (now - 650 min)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        base = now - timedelta(minutes=200)
        n = 100
        # Ostium (A) — escrivim al store
        for i in range(n):
            c = _candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.05 + (i % 3) * 0.0001)
            store.append(c)

        # Dukascopy (B) — fixture idèntic → COMPATIBLE
        candles_b = [
            _candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.05 + (i % 3) * 0.0001)
            for i in range(n)
        ]

        result = asyncio.run(
            run_compat(
                symbol="EURUSD",
                window_minutes=650,
                datafiles_root=root,
                broker="gtrade",
                candles_b_override=candles_b,
            )
        )

        assert result.get("registry_updated") is True
        assert result.get("ostium_primary_allowed") is True
        assert result.get("status") == "PASS"

        registry_path = Path(root) / "compat_reports" / "ostium_compat_registry.json"
        assert registry_path.exists()
        with open(registry_path) as f:
            reg = json.load(f)
        assert "EURUSD" in reg
        assert reg["EURUSD"]["status"] == "PASS"
        assert reg["EURUSD"]["ostium_primary_allowed"] is True
        print("✓ post-compat registry updated (PASS) OK")


def test_post_compat_soak_exit_coherent():
    """Soak eval existent no es trenca; post-compat no modifica exit code del soak."""
    # Només verifiquem que _run_post_compat retorna dict coherent
    with tempfile.TemporaryDirectory() as tmp:
        root = str(Path(tmp) / "datafiles")
        Path(root).mkdir(parents=True, exist_ok=True)
        result = _run_post_compat(
            compat_symbol="EURUSD",
            compat_candles=100,
            datafiles_root=root,
            broker="gtrade",
        )
        assert "symbol" in result
        assert "verdict" in result
        assert "ostium_primary_allowed" in result
        assert result["symbol"] == "EURUSD"
        print("✓ soak exit coherent OK")


def main():
    test_post_compat_skip_when_no_candles()
    test_post_compat_registry_updated_with_fixtures()
    test_post_compat_soak_exit_coherent()
    print("\n✓ All ostium_post_compat_hook tests passed")


if __name__ == "__main__":
    main()
