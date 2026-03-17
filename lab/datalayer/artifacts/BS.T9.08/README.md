# BS.T9.08 — Primera execució RAW Dukascopy (job + monitor + fs-check)

Script únic (arxivat): `./scripts/_archive/2026-03-raw-deprecated/run_t908_raw_first_run.sh` — RAW endpoints eliminats 2026-03.

## Modes

| Mode | Descripció |
|------|------------|
| (sense args) | PILOT 2026-02-01 → 2026-02-03 (EURUSD) + monitor fins done + fs-check |
| `--full-5y` | Job 5y (2021-03-03 → 2026-03-03) + monitor + fs-check |
| `--status` | GET /data/raw/dukascopy/status |
| `--job JOB_ID` | GET /data/raw/dukascopy/jobs/{id} |
| `--fs-check` | Comprovar FS: .bi5, manifest, watermark, absència de .tmp |

## Artifacts

| Fitxer | Descripció |
|--------|------------|
| `pilot_job.json` | Snapshot final GET job (pilot) |
| `full_job.json` | Snapshot final GET job (si s'ha executat --full-5y) |
| `job_id.txt` | job_id del darrer job executat |
| `fs_check.txt` | Comptatge .bi5, watermark, .tmp |
| `run.log` | Log de l'execució (pilot o --full-5y) |
| `final_report.json` | Resum T9.08.1: job_id, days_done/skipped/failed, retries, fs_check (tmp_count, bi5_eurusd, watermark) |
| `final_report.md` | Resum humà del finalize (retry day, failed_sense_retry si aplica) |

## Env

- `DATAFILES_ROOT` — arrel; RAW root derivat: `${DATAFILES_ROOT}/dukascopy_raw/m1_bi5_bid`
- `SYMBOLS` — símbols per sync (default intern EURUSD,XAUUSD)
- `BASE_URL` — gateway (default http://localhost:8081)
- `ARTIFACTS_DIR` — directori artifacts (default lab/datalayer/artifacts/BS.T9.08)

## DoD

- PILOT: status=done + fs-check OK (tmp_count=0, watermark present, bi5 present)
- Si --full-5y executat: job_id documentat (done o running)
- docs/ESTAT.md actualitzat amb evidència (job_id, status, tmp_count, watermark last_complete_day, bi5_count)

## Registre evidència (per ESTAT.md)

Després d’executar el pilot (o --full-5y), omplir a `docs/ESTAT.md` (entrada T9.08):

- **DATAFILES_ROOT:** (valor usat)
- **Comanda (deprecada):** `./scripts/_archive/2026-03-raw-deprecated/run_t908_raw_first_run.sh` [o `--full-5y`] — RAW eliminat.
- **job_id:** (de job_id.txt)
- **Resultat:** status final (done/running/failed), tmp_count, watermark last_complete_day, bi5_count

## T9.08.1 Finalize

Una sola comanda (deprecada): `./scripts/_archive/2026-03-raw-deprecated/run_t908_finalize.sh [--job JOB_ID]` — RAW eliminat. job_id per defecte: `job_id.txt`.

- Si el job no és `done`: imprimeix "still running" i surt (0).
- Si `done`: fs-check, si days_failed>0 retry 1 dia (data de last_error), escriu `final_report.json` + `final_report.md`, actualitza ESTAT.
