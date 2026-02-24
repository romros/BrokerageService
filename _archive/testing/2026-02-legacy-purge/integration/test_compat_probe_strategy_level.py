#!/usr/bin/env python3
"""
P6 — compat_probe v2 (Gate A + Gate B)

Compara Primary (candle_store) vs Dukascopy en 72h de solapament.
Mètriques estratègia-agnòstiques per validar si mixed stitching és segur.

Opt-in: --include-compat-probe
Preflight: SKIP exit 2 si entorn no preparat.

Output: datafiles/compat_probe/<ts>_compat_probe_<symbol>_72h.log

Ús:
  python3 testing/integration/test_compat_probe_strategy_level.py
  ./test.sh testing/run_all.py --include-compat-probe
"""
import asyncio
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from foundation.utils.file_permissions import set_host_readable_permissions
from testing.helpers.dukascopy_test_env import EXIT_SKIP, preflight_compat_probe

WINDOW_HOURS = 72
EXPECTED_MINUTES = 72 * 60  # 4320
GATE_A_MISSING_MAX = 4  # ≤4 min per 72h (0.1%)
SYMBOLS = ["EURUSD", "XAUUSD"]

# Gate B thresholds (AGENTS §2.7.6)
THRESHOLDS = {
    "EURUSD": {
        "direction_mismatch": 0.01,
        "corr_min": 0.985,
        "vol_ratio_min": 0.92,
        "vol_ratio_max": 1.08,
        "range_ratio_min": 0.92,
        "range_ratio_max": 1.08,
        "p95_range_diff_max": 0.00008,  # 0.8 pip EURUSD
    },
    "XAUUSD": {
        "direction_mismatch": 0.01,
        "corr_min": 0.98,
        "vol_ratio_min": 0.90,
        "vol_ratio_max": 1.10,
        "range_ratio_min": 0.90,
        "range_ratio_max": 1.10,
        "p95_range_diff_max": 0.10,  # 10 cèntims USD
    },
}


def _compute_metrics(primary: list, fallback: list, symbol: str) -> dict:
    """primary, fallback: list of {ts, open, high, low, close, volume}."""
    by_ts = {}
    for c in primary:
        by_ts[c["ts"]] = {"p": c, "f": None}
    for c in fallback:
        if c["ts"] in by_ts:
            by_ts[c["ts"]]["f"] = c
        else:
            by_ts[c["ts"]] = {"p": None, "f": c}

    aligned = [(ts, d["p"], d["f"]) for ts, d in sorted(by_ts.items()) if d["p"] and d["f"]]
    if len(aligned) < 100:
        return {"aligned_count": len(aligned), "gate_a_pass": False, "gate_b_pass": False}

    # Features per minut
    ret_p, ret_f = [], []
    range_p, range_f = [], []
    direction_mismatch = 0
    range_diffs = []

    for ts, p, f in aligned:
        ret_p_val = math.log(p["close"] / p["open"]) if p["open"] else 0
        ret_f_val = math.log(f["close"] / f["open"]) if f["open"] else 0
        ret_p.append(ret_p_val)
        ret_f.append(ret_f_val)

        rp = (p["high"] - p["low"]) / p["close"] if p["close"] else 0
        rf = (f["high"] - f["low"]) / f["close"] if f["close"] else 0
        range_p.append(rp)
        range_f.append(rf)

        if (ret_p_val > 0) != (ret_f_val > 0):
            direction_mismatch += 1

        if symbol == "EURUSD":
            range_diffs.append(abs((p["high"] - p["low"]) - (f["high"] - f["low"])))
        else:
            range_diffs.append(abs((p["high"] - p["low"]) - (f["high"] - f["low"])))

    n = len(aligned)
    dir_rate = direction_mismatch / n if n else 0

    def _std(x):
        if len(x) < 2:
            return 0
        m = sum(x) / len(x)
        return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))

    def _median(x):
        s = sorted(x)
        m = len(s) // 2
        return (s[m] + s[m - 1]) / 2 if len(s) % 2 == 0 else s[m]

    vol_std_p = _std(ret_p)
    vol_std_f = _std(ret_f)
    vol_ratio = vol_std_f / vol_std_p if vol_std_p else 1.0

    med_range_p = _median(range_p)
    med_range_f = _median(range_f)
    range_ratio = med_range_f / med_range_p if med_range_p else 1.0

    corr = 0
    if _std(ret_p) > 0 and _std(ret_f) > 0:
        m_p = sum(ret_p) / n
        m_f = sum(ret_f) / n
        cov = sum((ret_p[i] - m_p) * (ret_f[i] - m_f) for i in range(n)) / n
        corr = cov / (_std(ret_p) * _std(ret_f))

    range_diffs_sorted = sorted(range_diffs)
    p95_idx = int(0.95 * len(range_diffs_sorted))
    p95_range_diff = range_diffs_sorted[p95_idx] if range_diffs_sorted else 0

    th = THRESHOLDS.get(symbol, THRESHOLDS["EURUSD"])
    gate_b = (
        dir_rate <= th["direction_mismatch"]
        and corr >= th["corr_min"]
        and th["vol_ratio_min"] <= vol_ratio <= th["vol_ratio_max"]
        and th["range_ratio_min"] <= range_ratio <= th["range_ratio_max"]
        and p95_range_diff <= th["p95_range_diff_max"]
    )

    return {
        "aligned_count": n,
        "direction_mismatch_rate": dir_rate,
        "corr_ret": corr,
        "vol_ratio": vol_ratio,
        "range_ratio": range_ratio,
        "p95_range_diff": p95_range_diff,
        "gate_b_pass": gate_b,
    }


def _candles_to_dicts(candles) -> list:
    return [
        {
            "ts": int(c.timestamp.timestamp()) if hasattr(c.timestamp, "timestamp") else c["ts"],
            "open": c.open if hasattr(c, "open") else c["open"],
            "high": c.high if hasattr(c, "high") else c["high"],
            "low": c.low if hasattr(c, "low") else c["low"],
            "close": c.close if hasattr(c, "close") else c["close"],
            "volume": getattr(c, "volume", 0) or c.get("volume", 0),
        }
        for c in candles
    ]


async def _run_probe():
    from foundation.config.constants import CANONICAL_TIMEZONE, CANONICAL_TIMEZONE_NAME
    from infrastructure.storage.csv_store import CSVCandleStore
    from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider  # lazy: evita carregar P6 si preflight skip

    root = os.getenv("DATAFILES_ROOT", "datafiles")
    broker = os.getenv("PRIMARY_BROKER", "lighter")  # Primary per EURUSD/XAU és Lighter
    store = CSVCandleStore(root_path=root, broker=broker, canonical_tz=CANONICAL_TIMEZONE_NAME)
    provider = DukascopyBackfillProvider(cache_root=root)

    end = datetime.now(CANONICAL_TIMEZONE)
    start = end - timedelta(hours=WINDOW_HOURS)
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    start_ts = (start_ts // 60) * 60
    end_ts = (end_ts // 60) * 60
    start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)

    log_dir = Path(root) / "compat_probe"
    log_dir.mkdir(parents=True, exist_ok=True)
    set_host_readable_permissions(log_dir)
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    all_pass = True
    for symbol in SYMBOLS:
        # Primary
        rng = store.read_range(symbol, start_dt, end_dt, validate_gaps=True)
        primary = _candles_to_dicts(rng.candles)

        # Fallback
        try:
            fallback_candles = await provider.fetch_ohlcv(symbol, start_dt, end_dt)
            fallback = _candles_to_dicts(fallback_candles)
        except Exception as e:
            print(f"  {symbol}: Dukascopy error: {e}")
            all_pass = False
            continue

        # Gate A
        primary_ts = set(c["ts"] for c in primary)
        fallback_ts = set(c["ts"] for c in fallback)
        missing_fallback = len(primary_ts - fallback_ts)
        duplicate_primary = len(primary) - len(primary_ts)
        duplicate_fallback = len(fallback) - len(fallback_ts)
        ts_step_errors = 0
        for i in range(1, len(primary)):
            if primary[i]["ts"] - primary[i - 1]["ts"] != 60:
                ts_step_errors += 1

        gate_a = (
            duplicate_primary == 0
            and duplicate_fallback == 0
            and ts_step_errors == 0
            and missing_fallback <= GATE_A_MISSING_MAX
        )

        metrics = _compute_metrics(primary, fallback, symbol)
        metrics["duplicate_minutes_primary"] = duplicate_primary
        metrics["duplicate_minutes_fallback"] = duplicate_fallback
        metrics["ts_step_errors"] = ts_step_errors
        metrics["missing_fallback_minutes"] = missing_fallback
        metrics["gate_a_pass"] = gate_a

        status = "PASS" if (gate_a and metrics.get("gate_b_pass", False)) else "FAIL"
        if status == "FAIL":
            all_pass = False

        # P7: Actualitzar compat_registry.json (append/overwrite per símbol)
        registry_path = log_dir / "compat_registry.json"
        registry_data = {}
        if registry_path.exists():
            try:
                with open(registry_path) as rf:
                    registry_data = json.load(rf)
            except (json.JSONDecodeError, OSError):
                pass
        if not isinstance(registry_data, dict):
            registry_data = {}
        registry_data[symbol] = {
            "status": status,
            "asof_ts": int(datetime.now(timezone.utc).timestamp()),
            "window_hours": WINDOW_HOURS,
        }
        with open(registry_path, "w") as rf:
            json.dump(registry_data, rf, indent=2)
        set_host_readable_permissions(registry_path)

        # Log
        log_path = log_dir / f"{ts_str}_compat_probe_{symbol}_72h.log"
        with open(log_path, "w") as f:
            f.write(f"compat_probe {symbol} 72h\n")
            f.write(f"timestamp={ts_str}\n")
            f.write(f"gate_a_pass={gate_a}\n")
            f.write(f"gate_b_pass={metrics.get('gate_b_pass', False)}\n")
            f.write(f"status={status}\n")
            f.write(f"aligned_count={metrics.get('aligned_count', 0)}\n")
            f.write(f"duplicate_minutes_primary={duplicate_primary}\n")
            f.write(f"duplicate_minutes_fallback={duplicate_fallback}\n")
            f.write(f"ts_step_errors={ts_step_errors}\n")
            f.write(f"missing_fallback_minutes={missing_fallback}\n")
            f.write(f"direction_mismatch_rate={metrics.get('direction_mismatch_rate', 0):.4f}\n")
            f.write(f"corr_ret={metrics.get('corr_ret', 0):.4f}\n")
            f.write(f"vol_ratio={metrics.get('vol_ratio', 0):.4f}\n")
            f.write(f"range_ratio={metrics.get('range_ratio', 0):.4f}\n")
            f.write(f"p95_range_diff={metrics.get('p95_range_diff', 0):.6f}\n")
        set_host_readable_permissions(log_path)

        print(f"  {symbol}: {status}")
        print(f"    gate_a={gate_a} gate_b={metrics.get('gate_b_pass')}")
        print(f"    aligned={metrics.get('aligned_count')} missing_fallback={missing_fallback} ts_step_errors={ts_step_errors}")
        print(f"    direction_mismatch={metrics.get('direction_mismatch_rate', 0):.2%} corr={metrics.get('corr_ret', 0):.4f}")
        print(f"    vol_ratio={metrics.get('vol_ratio')} range_ratio={metrics.get('range_ratio')} p95_range_diff={metrics.get('p95_range_diff')}")
        print(f"    log: {log_path}")

    return all_pass


def main():
    print("=" * 60)
    print("P6 — compat_probe v2 (Gate A + Gate B)")
    print("=" * 60)

    ok, reason = asyncio.run(preflight_compat_probe())
    if not ok:
        print(f"  SKIP: {reason}")
        sys.exit(EXIT_SKIP)

    print("  Preflight OK")
    all_pass = asyncio.run(_run_probe())
    print()
    if all_pass:
        print("  ✓ compat_probe PASS")
        sys.exit(0)
    else:
        print("  ✗ compat_probe FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
