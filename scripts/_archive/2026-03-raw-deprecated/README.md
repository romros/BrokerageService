# scripts/_archive/2026-03-raw-deprecated/

**Propòsit:** Arxivat per traçabilitat històrica. **No utilitzar operativament.**

Aquests scripts depenien del flux RAW Dukascopy antic (`/data/raw/dukascopy/*`). Els endpoints i directoris RAW associats van ser eliminats el 2026-03-03 (veure `AGENTS_ARQUITECTURA.md` changelog).

**Scripts arxivats:**
- `run_t908_raw_first_run.sh` — Primera execució RAW sync (job + monitor)
- `run_t908_finalize.sh` — Finalització job RAW
- `watch_t910_raw_job.sh` — Monitor de job RAW

**Motiu:** La capa RAW és interna; no s'exposa per API. El sync Dukascopy ara es fa via `POST /data/sync` i altres camins documentats a `docs/ESTAT.md`.
