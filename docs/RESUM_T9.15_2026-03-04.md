# Resum T9.15 — Gate SQ↔BS M1 parity (2026-03-04)

## Què s'ha fet

1. **Gate SQ↔BS M1 parity** — Compara candles M1 SQ (CSV export) vs BS (GET /data/ohlcv)
2. **Investigació 7 barres extra_in_bs** — 2025-03-07 01:46–01:52 UTC; SQ no les exporta
3. **Investigació .dat** — Format propietari SQ; no és SQL ni cap format estàndard
4. **Validació** — Per totes les veles SQ tenim la mateixa; les 7 extra són defecte SQ
5. **Docs actualitzats** — DATA_PARITY_GATES, ESTAT; secció Parquet dual + market_closed

## Com ha quedat

### Paritat
- **missing_in_bs = 0** — Totes les barres SQ tenen correspondència a BS
- **mismatches = 0** — Preus idèntics en timestamps comuns
- **extra_in_bs = 7** — BS té 7 barres més que SQ (defecte SQ, no nostre)
- **Policy intersection → PASS** — Certificable sense resoldre el buit SQ

### Parquet
| Root | Env | Estat |
|------|-----|-------|
| `historical_parquet` | `legacy` | Antic (v1) |
| `historical_parquet_ticks_v1` | `ticks` | **Actiu** (v2, cutover) |

**Tenim ambdós.** El cutover és `DUKASCOPY_PARQUET_ACTIVE=ticks` al docker-compose.split.yml.

### Candles mercat tancat
- **Parquet:** Pot contenir candles de mercat tancat (BI5 inclou dissabtes/diumenges)
- **API:** Filtra per `is_market_open()` abans de retornar — **no retorna** candles de sessió tancada
- **Correcte:** La API és la vista neta; el Parquet és raw

### Fitxers pujats a GitHub
- `lab/datalayer/` — sq_bs_m1_parity_gate.py, dukascopy_gap_audit.py
- `lab/paritat_SQ_dukascopy/` — validate_parity, download_bi5, reconstruct_m1
- `lab/bi5_vs_sqcli/` — run.sh, README
- `scripts/run_t915*`, `run_t916*`, `run_t918*`, `run_t842*`, etc.
- `docs/DATA_PARITY_GATES.md`, `docs/ESTAT.md`
- `.gitignore` — lab/out/, artifacts, sq_decompiled

### Exclòs (gitignore)
- `lab/out/` — Artifacts generats localment
- `lab/bi5_vs_sqcli/artifacts/`, `lab/gold/artifacts/`
- `lab/runner/out_compare/sq_decompiled/`, `jadx.zip`
- `lab/ostium/output/`, `plan.json`
