#!/usr/bin/env python3
"""
T6.10 — Rebuild candles XAUUSD des de ticks JSONL aplicant el gate T6.9.

Llegeix ticks del tick_recorder (JSONL daily), aplica el market_hours gate
(minute_start market_open → inclou; market_closed → ignora), reconstrueix
candles 1m i les escriu al CSV store via patch() (merge, preferint nova dada).

Genera:
  - Backup del CSV original a _archive/ (timestamped)
  - Artifact report JSON: ticks_read, minutes_rebuilt, candles_written, spikes_fixed
  - Reescriu les candles del rang al store

Ús:
  python3 application/tools/ostium_rebuild_candles_from_ticks.py \\
    --symbol XAUUSD \\
    --from 2026-02-18T00:00:00Z \\
    --to 2026-02-26T00:00:00Z \\
    --ticks-root datafiles/realtime_datalayer/ticks \\
    --candles-root datafiles/realtime_datalayer \\
    --broker candles \\
    --dry-run

  Afegir --write per executar el patch.
"""

import argparse
import json
import os
import shutil
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apps.realtime_datalayer.market_hours.engine import get_market_state_ny
from domain.models import Candle
from foundation.logging import get_logger
from infrastructure.storage.csv_store import CSVCandleStore

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Funcions pures (testables 0-network)
# ---------------------------------------------------------------------------

def _parse_ticks_jsonl(path: Path) -> List[Tuple[int, float]]:
    """Llegeix ticks d'un fitxer JSONL. Retorna llista de (ts_epoch, price)."""
    ticks = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ticks.append((int(d["ts"]), float(d["price"])))
            except (KeyError, ValueError, json.JSONDecodeError):
                pass
    return ticks


def _load_ticks_for_range(
    ticks_root: Path,
    symbol: str,
    from_ts: int,
    to_ts: int,
) -> List[Tuple[int, float]]:
    """
    Carrega ticks de tots els fitxers JSONL del rang [from_ts, to_ts).
    Iterea per directoris daily/YYYYMMDD/{symbol}.jsonl.
    """
    all_ticks: List[Tuple[int, float]] = []
    daily_dir = ticks_root / "daily"
    if not daily_dir.exists():
        return all_ticks

    for day_dir in sorted(daily_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        jsonl = day_dir / f"{symbol}.jsonl"
        if not jsonl.exists():
            continue
        ticks = _parse_ticks_jsonl(jsonl)
        # Filtra per rang
        filtered = [(ts, p) for ts, p in ticks if from_ts <= ts < to_ts]
        all_ticks.extend(filtered)

    # Ordenar per timestamp (els fitxers ja haurien d'estar ordenats, però per seguretat)
    all_ticks.sort(key=lambda x: x[0])
    return all_ticks


def _bucket_ticks(ticks: List[Tuple[int, float]]) -> Dict[int, List[float]]:
    """
    Agrega ticks per minute_start = (ts // 60) * 60.
    Retorna dict minute_start → [prices...] en ordre d'arribada.
    """
    buckets: Dict[int, List[float]] = {}
    for ts, price in ticks:
        bucket = (ts // 60) * 60
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append(price)
    return buckets


def _is_market_open_for_minute(symbol: str, minute_ts: int) -> bool:
    """Gate market_hours per minute_start. Equivalent al T6.9 del recorder."""
    try:
        result = get_market_state_ny(symbol, minute_ts)
        return result.state == "open"
    except Exception:
        return True  # failsafe: inclou si engine falla


def _filter_spike_prices(prices: List[float], spike_pct_threshold: float) -> List[float]:
    """
    Filtra preus que cauen per sota de median * spike_pct_threshold.
    Detecta i elimina el 'break_price' que Ostium retorna al tancament de mercat.
    Retorna la llista filtrada (manté l'ordre original).
    Si tots els preus cauen sota el threshold, retorna la llista original (failsafe).
    """
    if len(prices) < 2:
        return prices
    median = statistics.median(prices)
    threshold = median * spike_pct_threshold
    clean = [p for p in prices if p >= threshold]
    if not clean:
        return prices  # failsafe: no filtrar si tots són sota el threshold
    return clean


def rebuild_candles_from_ticks(
    ticks: List[Tuple[int, float]],
    symbol: str,
    from_ts: int,
    to_ts: int,
    spike_pct_threshold: float = 0.99,
) -> Tuple[List[Candle], Dict]:
    """
    Funció pura de rebuild (testable 0-network amb market_hours_fn injectable).

    Args:
        ticks: llista de (ts_epoch, price) ja filtrats al rang
        symbol: símbol (ex: XAUUSD)
        from_ts: start epoch (inclusiu)
        to_ts: end epoch (exclusiu)
        spike_pct_threshold: preus < median * threshold s'ignoren del bucket (default 0.99)

    Returns:
        (candles, stats) on stats té:
          ticks_read, buckets_total, buckets_open, buckets_closed, candles_built, ticks_spike_filtered
    """
    buckets = _bucket_ticks(ticks)

    candles: List[Candle] = []
    buckets_open = 0
    buckets_closed = 0
    ticks_spike_filtered = 0

    for minute_ts in sorted(buckets.keys()):
        if not (from_ts <= minute_ts < to_ts):
            continue
        prices = buckets[minute_ts]
        if not prices:
            continue

        if not _is_market_open_for_minute(symbol, minute_ts):
            buckets_closed += 1
            continue

        # Filtra spike ticks (break_price de l'API quan el mercat tanca)
        clean_prices = _filter_spike_prices(prices, spike_pct_threshold)
        ticks_spike_filtered += len(prices) - len(clean_prices)

        buckets_open += 1
        o = clean_prices[0]
        h = max(clean_prices)
        l = min(clean_prices)
        c = clean_prices[-1]

        # Validació OHLC bàsica (evitar Candle validation error)
        if h < l or o > h or o < l or c > h or c < l:
            # Corregir inconsistències menors (rounding)
            h = max(o, h, l, c)
            l = min(o, h, l, c)

        ts_dt = datetime.fromtimestamp(minute_ts, tz=timezone.utc)
        candles.append(Candle(
            symbol=symbol,
            timestamp=ts_dt,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=0.0,
            is_closed=True,
        ))

    stats = {
        "ticks_read": len(ticks),
        "buckets_total": len(buckets),
        "buckets_open": buckets_open,
        "buckets_closed": buckets_closed,
        "candles_built": len(candles),
        "ticks_spike_filtered": ticks_spike_filtered,
    }
    return candles, stats


# ---------------------------------------------------------------------------
# Backup i write
# ---------------------------------------------------------------------------

def _backup_csv_range(
    store: CSVCandleStore,
    symbol: str,
    from_dt: datetime,
    to_dt: datetime,
    archive_dir: Path,
) -> Optional[Path]:
    """
    Backup dels CSV mensuals afectats pel rang a archive_dir.
    Retorna el directori del backup o None si no hi ha fitxers.
    """
    ts_label = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = archive_dir / f"{ts_label}_{symbol}_rebuild_backup"

    # Determinar mesos afectats
    months_affected = set()
    cur = from_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur <= to_dt:
        months_affected.add((cur.year, cur.month))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)

    backed_up = []
    for year, month in sorted(months_affected):
        dt = datetime(year, month, 1, tzinfo=store.canonical_tz)
        csv_path = store._get_file_path(symbol, dt)
        if csv_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            dest = backup_dir / f"{year}_{month:02d}.csv"
            shutil.copy2(csv_path, dest)
            backed_up.append(str(dest))
            logger.info("backup %s → %s", csv_path, dest)

    if backed_up:
        return backup_dir
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="T6.10 — Rebuild candles XAUUSD des de ticks JSONL (T6.9 gate)"
    )
    parser.add_argument("--symbol", default="XAUUSD", help="Símbol a reparar (default XAUUSD)")
    parser.add_argument("--from", dest="from_ts", required=True,
                        help="Inici rang (ISO UTC, ex: 2026-02-18T00:00:00Z)")
    parser.add_argument("--to", dest="to_ts", required=True,
                        help="Fi rang exclusiu (ISO UTC, ex: 2026-02-26T00:00:00Z)")
    parser.add_argument("--ticks-root", default="datafiles/realtime_datalayer/ticks",
                        help="Path arrel dels ticks JSONL (conté daily/YYYYMMDD/)")
    parser.add_argument("--candles-root", default="datafiles/realtime_datalayer",
                        help="Datafiles root pel CandleStore")
    parser.add_argument("--broker", default="candles",
                        help="Broker/venue del CandleStore (default 'candles')")
    parser.add_argument("--spike-threshold", type=float, default=0.99,
                        help="Filtre spike: preus < median*threshold s'eliminen del bucket (default 0.99)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Només mostra estadístiques, no escriu res")
    parser.add_argument("--write", action="store_true",
                        help="Executa backup + patch al store")
    parser.add_argument("--out", default=None,
                        help="Path output per l'artifact report JSON (default: auto)")
    args = parser.parse_args()

    # Parse dates
    from_dt = datetime.fromisoformat(args.from_ts.replace("Z", "+00:00"))
    to_dt = datetime.fromisoformat(args.to_ts.replace("Z", "+00:00"))
    from_epoch = int(from_dt.timestamp())
    to_epoch = int(to_dt.timestamp())

    # Paths
    base_dir = Path(__file__).parent.parent.parent
    ticks_root = base_dir / args.ticks_root
    candles_root = base_dir / args.candles_root

    print(f"T6.10 Rebuild {args.symbol} {args.from_ts} → {args.to_ts}")
    print(f"  ticks_root: {ticks_root}")
    print(f"  candles_root: {candles_root}")
    print(f"  spike_threshold: {args.spike_threshold}")
    print(f"  dry_run: {args.dry_run}")
    print()

    # 1. Carregar ticks
    print("1. Carregant ticks...")
    ticks = _load_ticks_for_range(ticks_root, args.symbol, from_epoch, to_epoch)
    print(f"   ticks_read={len(ticks)}")
    if not ticks:
        print("   ERROR: no hi ha ticks pel rang especificat.")
        sys.exit(1)

    # 2. Rebuild candles
    print("2. Reconstruint candles (market_hours gate T6.9 + spike filter)...")
    candles, stats = rebuild_candles_from_ticks(
        ticks, args.symbol, from_epoch, to_epoch,
        spike_pct_threshold=args.spike_threshold,
    )
    print(f"   ticks_read={stats['ticks_read']}")
    print(f"   buckets_total={stats['buckets_total']}")
    print(f"   buckets_open={stats['buckets_open']} (candles a escriure)")
    print(f"   buckets_closed={stats['buckets_closed']} (ignorats)")
    print(f"   ticks_spike_filtered={stats['ticks_spike_filtered']} (break_price eliminats)")
    print(f"   candles_built={stats['candles_built']}")

    # 3. Comparar amb store existent (detectar spikes corregits)
    print("3. Comparant amb store existent...")
    store = CSVCandleStore(str(candles_root), args.broker)
    existing_range = store.read_range(args.symbol, from_dt, to_dt, validate_gaps=False)
    existing_by_ts = {int(c.timestamp.timestamp()): c for c in existing_range.candles}

    spikes_fixed = []
    candles_new = []
    candles_updated = []

    for c in candles:
        ts_ep = int(c.timestamp.timestamp())
        if ts_ep in existing_by_ts:
            old = existing_by_ts[ts_ep]
            diff_close = abs(old.close - c.close)
            diff_low = abs(old.low - c.low)
            if diff_close > 10.0 or diff_low > 10.0:
                spikes_fixed.append({
                    "ts_utc": c.timestamp.isoformat(),
                    "old_close": round(old.close, 5),
                    "new_close": round(c.close, 5),
                    "diff_close": round(diff_close, 5),
                    "old_low": round(old.low, 5),
                    "new_low": round(c.low, 5),
                    "diff_low": round(diff_low, 5),
                })
                candles_updated.append(c)
            elif diff_close > 0.001 or diff_low > 0.001:
                candles_updated.append(c)
        else:
            candles_new.append(c)

    print(f"   candles_new={len(candles_new)}")
    print(f"   candles_updated={len(candles_updated)}")
    print(f"   spikes_fixed={len(spikes_fixed)}")
    if spikes_fixed:
        print("   SPIKES DETECTATS I CORREGITS:")
        for s in spikes_fixed:
            print(f"     {s['ts_utc']}: close {s['old_close']}→{s['new_close']} (diff={s['diff_close']:.2f})")

    # 4. Artifact report
    ts_label = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_path = (
        base_dir / "datafiles" / "realtime_datalayer" / "artifacts" / "compat" /
        f"{ts_label}_xauusd_rebuild_from_ticks_report.json"
    ) if args.out is None else Path(args.out)

    report = {
        "tool": "ostium_rebuild_candles_from_ticks",
        "symbol": args.symbol,
        "from_ts": args.from_ts,
        "to_ts": args.to_ts,
        "spike_pct_threshold": args.spike_threshold,
        "dry_run": args.dry_run,
        "stats": stats,
        "candles_new": len(candles_new),
        "candles_updated": len(candles_updated),
        "spikes_fixed": len(spikes_fixed),
        "spikes_detail": spikes_fixed,
        "written": False,
    }

    if args.dry_run:
        print("\nDRY-RUN: no s'escriu res.")
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with open(artifact_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Artifact: {artifact_path}")
        sys.exit(0)

    if not args.write:
        print("\n[!] Usa --write per executar el patch. O --dry-run per mode segur.")
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with open(artifact_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Artifact: {artifact_path}")
        sys.exit(0)

    # 5. Backup
    print("\n4. Backup dels CSV originals...")
    archive_dir = base_dir / "_archive"
    backup_dir = _backup_csv_range(store, args.symbol, from_dt, to_dt, archive_dir)
    if backup_dir:
        print(f"   backup: {backup_dir}")
        report["backup_dir"] = str(backup_dir)
    else:
        print("   [!] No s'han trobat CSV per fer backup (rang sense dades prèvies?)")

    # 6. Patch al store
    print("5. Patch al store (merge, prefer new data)...")
    written = store.patch(candles)
    print(f"   candles_patched={written}")
    report["written"] = True
    report["candles_patched"] = written

    # 7. Guardar artifact
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with open(artifact_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nArtifact report: {artifact_path}")

    print(f"\n✅ Rebuild complet: {stats['candles_built']} candles reconstruïdes, {len(spikes_fixed)} spikes corregits.")


if __name__ == "__main__":
    main()
