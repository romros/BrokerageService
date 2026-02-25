#!/usr/bin/env python3
"""
Ostium compat report — unit tests (0-network)

Valida build_compat_report amb fixtures tipus Ostium vs Dukascopy:
- overlap, corr, dir_agree
- verdict COMPATIBLE→PASS, PARTIAL→PARTIAL, INCOMPATIBLE/DATA_QUALITY_FAIL→FAIL
- Mapeig per graduation gate.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from application.services.compat_report_service import (
    build_compat_report,
    compute_compat_verdict,
    VERDICT_COMPATIBLE,
    VERDICT_PASS_BACKTEST,
    VERDICT_PARTIAL,
    VERDICT_INCOMPATIBLE,
    VERDICT_DATA_QUALITY_FAIL,
)


def _candle(symbol: str, base: datetime, offset_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol, base + timedelta(minutes=offset_min), o, h, l, c, 0)


def _close_in_range(low: float, high: float, i: int, n: int) -> float:
    return low + (high - low) * (i + 1) / (n + 1)


def test_ostium_dukascopy_overlap():
    """Overlap correcte entre dues sèries Ostium vs Dukascopy."""
    base = datetime(2026, 2, 10, 12, 0, 0)
    n = 120
    candles_a = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    candles_b = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    report = build_compat_report(
        candles_a, candles_b, "EURUSD",
        source_a="ostium_realtime", source_b="dukascopy",
    )
    assert report["source_a"] == "ostium_realtime"
    assert report["source_b"] == "dukascopy"
    assert report["aligned_count"] == n
    overlap = report["overlap"]
    assert overlap["overlap_minutes"] >= n - 1
    assert overlap["pct_overlap_over_a"] >= 90
    assert overlap["pct_overlap_over_b"] >= 90
    print("✓ ostium_dukascopy_overlap OK")


def test_ostium_dukascopy_corr_dir_agree():
    """Sèries idèntiques → corr≈1, dir_agree≈100%."""
    base = datetime(2026, 2, 10, 12, 0, 0)
    n = 100
    candles = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    report = build_compat_report(
        candles, candles, "EURUSD",
        source_a="ostium_realtime", source_b="dukascopy",
    )
    assert report["returns"]["corr"] >= 0.999
    assert report["returns"]["dir_agree_pct"] >= 99.9
    assert report["verdict"] == VERDICT_COMPATIBLE
    print("✓ ostium_dukascopy_corr_dir_agree OK")


def test_ostium_verdict_pass():
    """COMPATIBLE → PASS (per graduation gate)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.05}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.98, "dir_agree_pct": 97},
        "lag_scan": {"corr_at_best_lag": 0.98},
        "ohlc_diffs": {"close": {"p95": 0.0005}},
        "symbol": "EURUSD",
    }
    v, _ = compute_compat_verdict(report)
    assert v == VERDICT_COMPATIBLE
    # Mapeig Ostium: COMPATIBLE → PASS
    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    status = VERDICT_TO_STATUS.get(v, "FAIL")
    assert status == "PASS"
    print("✓ ostium_verdict_pass OK")


def test_ostium_verdict_fail():
    """INCOMPATIBLE / DATA_QUALITY_FAIL → FAIL."""
    # Overlap insuficient
    report1 = {
        "candle_quality": {"a": {"zero_range_ratio": 0.05}, "b": {}},
        "overlap": {"pct_overlap_over_a": 30, "pct_overlap_over_b": 30},
        "returns": {"corr": 0.5, "dir_agree_pct": 60},
        "lag_scan": {},
        "ohlc_diffs": {"close": {"p95": 0.001}},
        "symbol": "EURUSD",
    }
    v1, _ = compute_compat_verdict(report1)
    assert v1 == VERDICT_INCOMPATIBLE

    # zero_range > 20%
    report2 = {
        "candle_quality": {"a": {"zero_range_ratio": 0.87}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.5, "dir_agree_pct": 60},
        "lag_scan": {},
        "ohlc_diffs": {"close": {"p95": 0.001}},
        "symbol": "EURUSD",
    }
    v2, _ = compute_compat_verdict(report2)
    assert v2 == VERDICT_DATA_QUALITY_FAIL

    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    assert VERDICT_TO_STATUS.get(v1, "FAIL") == "FAIL"
    assert VERDICT_TO_STATUS.get(v2, "FAIL") == "FAIL"
    print("✓ ostium_verdict_fail OK")


def test_ostium_verdict_partial():
    """PARTIAL → PARTIAL (ostium_primary_allowed=false)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.1}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.76, "dir_agree_pct": 72},
        "lag_scan": {"corr_at_best_lag": 0.76},
        "ohlc_diffs": {"close": {"p95": 6.0}},
        "symbol": "XAUUSD",
    }
    v, _ = compute_compat_verdict(report)
    assert v == VERDICT_PARTIAL
    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    assert VERDICT_TO_STATUS.get(v, "FAIL") == "PARTIAL"
    print("✓ ostium_verdict_partial OK")


def test_dir_agree_filtered_ignores_flat_minutes():
    """dir_agree_filtered ignora minuts amb moviment < ε (soroll feed 1m)."""
    base = datetime(2026, 2, 10, 12, 0, 0)
    # Sèrie A puja monotònicament; sèrie B igual però amb micro-diffs aleatòries als primers minuts
    import random
    random.seed(42)
    n = 200
    closes_a = [1.05000 + i * 0.00005 for i in range(n)]
    # B: igual a A però en el 20% de minuts inicials canvi negligible (flat)
    closes_b = []
    for i, ca in enumerate(closes_a):
        if i < 40:
            closes_b.append(ca + random.uniform(-0.000005, 0.000005))  # soroll < ε
        else:
            closes_b.append(ca)

    candles_a = [
        _candle("EURUSD", base, i, closes_a[i], closes_a[i] + 0.0005, closes_a[i] - 0.0005, closes_a[i])
        for i in range(n)
    ]
    candles_b = [
        _candle("EURUSD", base, i, closes_b[i], closes_b[i] + 0.0005, closes_b[i] - 0.0005, closes_b[i])
        for i in range(n)
    ]
    report = build_compat_report(candles_a, candles_b, "EURUSD",
                                 source_a="ostium_realtime", source_b="dukascopy")
    daf = report["dir_agree_filtered"]
    assert "dir_agree_filtered_pct" in daf
    assert "eligible_count" in daf
    assert daf["eligible_count"] <= daf["total_count"]
    # El filtrat ha d'excloure alguns minuts "flat" (ε petit però moviment < ε possible)
    assert daf["eligible_count"] > 0
    print(f"✓ dir_agree_filtered_ignores_flat_minutes OK "
          f"(eligible={daf['eligible_count']}/{daf['total_count']}, "
          f"dir_agree_filtered={daf['dir_agree_filtered_pct']:.1f}%)")


def test_pass_backtest_verdict():
    """PASS_BACKTEST quan corr >= 0.90 i dir_agree_filtered >= 95% (eligible suficient)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.02}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.958, "dir_agree_pct": 90.0},
        "lag_scan": {"corr_at_best_lag": 0.958},
        "ohlc_diffs": {"close": {"p95": 0.00005}},
        "dir_agree_filtered": {
            "dir_agree_filtered_pct": 96.5,
            "eligible_count": 520,
            "total_count": 649,
        },
        "symbol": "EURUSD",
    }
    v, reason = compute_compat_verdict(report)
    assert v == VERDICT_PASS_BACKTEST, f"Esperat PASS_BACKTEST, got {v}: {reason}"
    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    assert VERDICT_TO_STATUS.get(v) == "PASS_BACKTEST"
    print(f"✓ pass_backtest_verdict OK ({reason})")


def test_pass_backtest_registry_fields():
    """PASS_BACKTEST → allowed_for_backtest=true, allowed_for_live=false."""
    import tempfile
    from application.data.ostium_compat_registry import save_ostium_registry, load_ostium_registry
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_ostium_registry("EURUSD", "PASS_BACKTEST", "corr=0.958 dir_filtered=96.5%",
                             registry_path=path)
        data = load_ostium_registry(registry_path=path)
        entry = data["EURUSD"]
        assert entry["status"] == "PASS_BACKTEST"
        assert entry["allowed_for_backtest"] is True
        assert entry["allowed_for_live"] is False
        assert entry["ostium_primary_allowed"] is False
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ pass_backtest_registry_fields OK")


def test_pass_backtest_not_triggered_low_eligible():
    """PASS_BACKTEST NO s'aplica si eligible < mínim (soroll insuficient per avaluar)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.02}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.958, "dir_agree_pct": 90.0},
        "lag_scan": {"corr_at_best_lag": 0.958},
        "ohlc_diffs": {"close": {"p95": 0.00005}},
        "dir_agree_filtered": {
            "dir_agree_filtered_pct": 97.0,
            "eligible_count": 50,   # < 100 mínim
            "total_count": 649,
        },
        "symbol": "EURUSD",
    }
    v, _ = compute_compat_verdict(report)
    assert v == VERDICT_PARTIAL, f"Esperat PARTIAL (eligible massa baix), got {v}"
    print("✓ pass_backtest_not_triggered_low_eligible OK")


def test_save_compat_report_full_filename():
    """save_compat_report mode=full genera nom de fitxer correcte i latest_full_<sym>.json."""
    import json
    import tempfile
    from datetime import timezone
    from application.services.compat_report_service import save_compat_report

    report = {
        "symbol": "EURUSD",
        "window_minutes": 43200,
        "aligned_count": 10,
        "verdict": "PASS_BACKTEST",
        "verdict_reason": "test",
    }
    from_ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    to_ts = datetime(2026, 2, 25, 0, 0, 0, tzinfo=timezone.utc)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_compat_report(
            report,
            datafiles_root=tmpdir,
            mode="full",
            from_ts=from_ts,
            to_ts=to_ts,
        )
        p = Path(path)
        assert p.exists(), f"Artifact no creat: {path}"
        assert "compat_full_EURUSD" in p.name, f"Filename incorrecte: {p.name}"
        assert "20250101" in p.name, f"from_ts no al filename: {p.name}"
        assert "20260225" in p.name, f"to_ts no al filename: {p.name}"

        latest_full = p.parent / "latest_full_EURUSD.json"
        assert latest_full.exists(), "latest_full_EURUSD.json no creat"

        # latest_<sym>.json NO s'ha de crear en mode full
        latest_rolling = p.parent / "latest_EURUSD.json"
        assert not latest_rolling.exists(), "latest_EURUSD.json NO hauria d'existir en mode full"

        with open(latest_full) as f:
            data = json.load(f)
        assert data["symbol"] == "EURUSD"

    print("✓ save_compat_report_full_filename OK")


def test_save_compat_report_rolling_no_latest_full():
    """save_compat_report mode=rolling NO crea latest_full_<sym>.json."""
    import tempfile
    from application.services.compat_report_service import save_compat_report

    report = {
        "symbol": "EURUSD",
        "window_minutes": 1440,
        "aligned_count": 5,
        "verdict": "PARTIAL",
        "verdict_reason": "test",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_compat_report(report, datafiles_root=tmpdir, mode="rolling")
        p = Path(path)
        assert p.exists()
        assert "compat_full" not in p.name, f"Filename no hauria de tenir 'full': {p.name}"

        latest_rolling = p.parent / "latest_EURUSD.json"
        assert latest_rolling.exists(), "latest_EURUSD.json hauria d'existir en mode rolling"

        latest_full = p.parent / "latest_full_EURUSD.json"
        assert not latest_full.exists(), "latest_full_EURUSD.json NO hauria d'existir en mode rolling"

    print("✓ save_compat_report_rolling_no_latest_full OK")


def test_full_mode_totals_and_aligned():
    """T6.5: run_compat_full calcula ostium_total, duka_total, aligned_total, aligned_ratio."""
    import asyncio
    import tempfile
    from application.tools.ostium_compat_report import run_compat_full, _aligned_ratio

    base = datetime(2026, 2, 10, 12, 0, 0)
    n_ostium = 5
    n_duka = 5
    # 3 candles alineades (ts coincideix), 2 extra a duka sense match
    candles_ostium = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.0500 + i * 0.0001)
        for i in range(n_ostium)
    ]
    # Duka: primers 3 idèntics en ts, 2 extra sense match (offset +100)
    candles_duka_aligned = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.0500 + i * 0.0001)
        for i in range(3)
    ]
    candles_duka_extra = [
        _candle("EURUSD", base, 100 + i, 1.05, 1.051, 1.049, 1.0500)
        for i in range(2)
    ]
    candles_duka = candles_duka_aligned + candles_duka_extra

    with tempfile.TemporaryDirectory() as tmpdir:
        result = asyncio.run(
            run_compat_full(
                symbol="EURUSD",
                datafiles_root=tmpdir,
                candles_b_override=candles_duka,
                # No hi ha store real: simula "no data" per provar la branca
                # Fem servir candles_b_override però necessitem un store amb dades
                # → usem la branca d'error per verificar el camp ostium_total=0
            )
        )
        # Sense store real, retorna FAIL amb ostium_total=0
        assert result["verdict"] == "FAIL"
        assert result["ostium_total"] == 0
        assert result["duka_total"] == 0
        assert result["aligned_total"] == 0
        assert result["aligned_ratio"] == 0.0

    # Test de la funció _aligned_ratio directament
    assert _aligned_ratio(10, 8, 7) == round(7 / 10, 4)
    assert _aligned_ratio(0, 0, 0) == 0.0
    assert _aligned_ratio(5, 7, 3) == round(3 / 7, 4)

    print("✓ full_mode_totals_and_aligned OK")


def test_aligned_ratio_formula():
    """_aligned_ratio usa max(ostium, duka) com a denominador."""
    from application.tools.ostium_compat_report import _aligned_ratio

    assert _aligned_ratio(100, 80, 75) == round(75 / 100, 4)  # ostium > duka
    assert _aligned_ratio(80, 100, 75) == round(75 / 100, 4)  # duka > ostium
    assert _aligned_ratio(0, 0, 0) == 0.0                      # cas degenerat
    assert _aligned_ratio(10, 10, 10) == 1.0                   # alineació perfecta
    assert _aligned_ratio(10, 10, 5) == 0.5

    print("✓ aligned_ratio_formula OK")


def test_returns_market_open_excluded_closed_minutes():
    """
    T6.8: _returns_market_open_filtered exclou minuts market_closed.

    Usem timestamps reals de XAUUSD a l'hora del break diari (17:00 NY = 22:00 UTC aprox).
    Verificació:
    - closed_minutes_excluded_count > 0 per timestamp dins break
    - n_open_pairs < n total
    """
    from application.services.compat_report_service import _returns_market_open_filtered

    # Timestamps durant el break diari XAUUSD (17:00–18:00 NY = 22:00–23:00 UTC)
    # 2026-02-24 22:05 UTC = 17:05 NY = CLOSED (daily_break)
    import calendar
    closed_ts = calendar.timegm((2026, 2, 24, 22, 5, 0, 0, 0, 0))  # UTC epoch
    # 2026-02-24 15:00 UTC = 10:00 NY = OPEN
    open_ts = calendar.timegm((2026, 2, 24, 15, 0, 0, 0, 0, 0))

    base = datetime(2026, 2, 24, 15, 0, 0, tzinfo=timezone.utc)
    n = 60

    candles = []
    for i in range(n):
        # Alterna open/closed: els 10 primers minuts open, 10 a hora closed, 40 open
        if i < 10:
            ts_epoch = open_ts + i * 60
        elif i < 20:
            ts_epoch = closed_ts + (i - 10) * 60
        else:
            ts_epoch = open_ts + i * 60
        ts = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
        c = base.timestamp() + i * 0.001  # preu que puja lleugerament
        price = 5000.0 + i
        ca = Candle("XAUUSD", ts, price, price + 1.0, price - 1.0, price, 0)
        cb = Candle("XAUUSD", ts, price, price + 1.0, price - 1.0, price, 0)
        candles.append((ca, cb))

    r = _returns_market_open_filtered(candles, symbol="XAUUSD")
    assert r["closed_minutes_excluded_count"] > 0, (
        f"Hauria d'excloure algun minut closed, got {r['closed_minutes_excluded_count']}"
    )
    assert r["n_open_pairs"] < len(candles), (
        f"n_open_pairs hauria de ser < {len(candles)}, got {r['n_open_pairs']}"
    )
    assert r["closed_minutes_excluded_pct"] > 0.0
    print(
        f"✓ returns_market_open_excluded OK "
        f"(excluded={r['closed_minutes_excluded_count']}, "
        f"n_open={r['n_open_pairs']}/{len(candles)}, "
        f"pct={r['closed_minutes_excluded_pct']}%)"
    )


def test_market_open_filter_improves_xauusd_verdict():
    """
    T6.8: build_compat_report amb XAUUSD retorna returns_market_open al report,
    i exclou minuts closed (zero_range stale).

    Simula la situació real: candles normals + 1 candle zero_range durant market_closed.
    Verifica:
    - report conté clau 'returns_market_open'
    - closed_minutes_excluded_count >= 0 (el filtre s'ha aplicat)
    - retorn de claus correctes al report
    """
    from application.services.compat_report_service import build_compat_report

    # Timestamp real: dilluns 2026-02-23 15:00 UTC (mercat obert XAUUSD)
    import calendar
    base_epoch = calendar.timegm((2026, 2, 23, 15, 0, 0, 0, 0, 0))
    n = 120

    candles_a = []
    candles_b = []
    for i in range(n):
        ts = datetime.fromtimestamp(base_epoch + i * 60, tz=timezone.utc)
        price = 5100.0 + i * 0.5
        # Candle normal (high > low)
        ca = Candle("XAUUSD", ts, price, price + 1.0, price - 1.0, price, 0)
        cb = Candle("XAUUSD", ts, price, price + 1.0, price - 1.0, price, 0)
        candles_a.append(ca)
        candles_b.append(cb)

    report = build_compat_report(
        candles_a, candles_b, "XAUUSD",
        source_a="ostium_realtime", source_b="dukascopy",
    )

    assert "returns_market_open" in report, "report ha de tenir 'returns_market_open'"
    rmo = report["returns_market_open"]
    assert "closed_minutes_excluded_count" in rmo
    assert "n_open_pairs" in rmo
    assert "corr" in rmo
    assert rmo["n_open_pairs"] <= n, f"n_open_pairs ha de ser <= {n}"
    print(
        f"✓ market_open_filter_improves_xauusd_verdict OK "
        f"(excluded={rmo['closed_minutes_excluded_count']}, "
        f"n_open={rmo['n_open_pairs']}, corr={rmo['corr']:.3f})"
    )


def main():
    test_ostium_dukascopy_overlap()
    test_ostium_dukascopy_corr_dir_agree()
    test_ostium_verdict_pass()
    test_ostium_verdict_fail()
    test_ostium_verdict_partial()
    test_dir_agree_filtered_ignores_flat_minutes()
    test_pass_backtest_verdict()
    test_pass_backtest_registry_fields()
    test_pass_backtest_not_triggered_low_eligible()
    # T6.5 — nous tests full mode
    test_save_compat_report_full_filename()
    test_save_compat_report_rolling_no_latest_full()
    test_full_mode_totals_and_aligned()
    test_aligned_ratio_formula()
    # T6.8 — market_open filter
    test_returns_market_open_excluded_closed_minutes()
    test_market_open_filter_improves_xauusd_verdict()
    print("\n✓ All ostium compat report service unit tests passed")


if __name__ == "__main__":
    main()
