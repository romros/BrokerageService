# T9.19 — Decommission historical_parquet legacy (2026-03-04)

## Què s'ha fet

1. **Config/routing:** `DuckDBQueryService` — ticks default únic; `legacy` → RuntimeError explícit
2. **API:** `get_sources` usa `duckdb_svc._root` (ticks); propaga error si legacy
3. **mixed_ohlcv_stitcher:** source label `dukascopy` (no historical_parquet)
4. **docker-compose:** Comentari T9.19; eliminat rollback legacy
5. **Script arxiu:** `scripts/run_t919_archive_legacy_parquet.sh`

## Arxivar legacy (manual)

**Quan:** Servei aturat (historical_datalayer no en marxa).

```bash
./scripts/run_t919_archive_legacy_parquet.sh
```

**Output:** `datafiles/_archive/historical_parquet_legacy_v1_YYYYMMDD_HHMMSS/`

## Smokes

```bash
# 1) sources
curl -sS http://localhost:8081/data/sources

# 2) OHLCV
curl -sS "http://localhost:8081/data/ohlcv/EURUSD?tf=1m&from=2026-01-10T00:00:00Z&to=2026-01-10T03:00:00Z&source=dukascopy" | head -c 300; echo

# 3) Gate T9.15 (opcional)
./scripts/run_t915_sq_bs_m1_parity_gate.sh --symbol EURUSD --from 2026-01-01 --to 2026-02-01 --policy intersection
```

## Commit

`git rev-parse HEAD` després del commit T9.19.

## Tests actualitzats

- `test_parquet_ticks_builder`: test_duckdb_ticks_default, test_duckdb_legacy_raises
- `test_duckdb_query.py`: _write_parquet → ticks path; source=dukascopy
- `test_mixed_stitching`, `test_data_ohlcv_long_range_parquet`, `test_backtest_parquet`: source=dukascopy; _write_parquet → ticks path
