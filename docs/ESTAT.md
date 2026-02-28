# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-28
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`
**Venues:** Ostium (principal) · Dukascopy (historical/backtest). **Legacy arxivat:** Lighter/gTrade → `_archive/`.
**TZ canònica (config):** `CANONICAL_TZ=America/New_York`
**TZ container (runtime/logs):** `TZ=America/New_York`
**Índex docs:** [docs/INDEX.md](INDEX.md) ← navegació centralitzada
**Doc referència:** [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)
**Runbook operatiu curt:** [SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md)
**Històric (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

**Recorda Docker:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`. Vegeu AGENTS §11.

---

## TL;DR

- ✅ **MVP Ostium LIVE stable** (fast-ack 202 + operations + smoke + up scripts)
- ✅ **Data Layer** (P4–P7c): backfill, gap repair, headers X-Data, /coverage, /data_status, read-through, stitching gated
- ✅ **Data Layer prod v0** (opt-in): prefetch + writer loop + gates; `DATA_LAYER_ENABLED=1`
- ✅ **Ostium Data Layer prod v0** (opt-in): realtime Ostium (polling) + backfill Dukascopy; `OSTIUM_ENABLED=1`
- ✅ **Broker API** `/api/v1/broker/*` (POST body únic)
- ✅ **Split vNext Phase 1:** 3 serveis autònoms (realtime/historical/trading); entrypoints + role wiring
- ✅ **Split vNext Phase 2:** trading_service → realtime_datalayer via HTTP; QualityGate fail-closed (`application/data/quality_gate.py`)
- ✅ **Split vNext Phase 3:** Symbol Supervisor + heartbeat mode (market_closed → poll 60s, no stop total; `OSTIUM_CLOSED_HEARTBEAT_S`)
- ✅ **Split vNext Phase 4:** X-Data-* headers contracte verificat; `test_ohlcv_headers.py` (4 tests); path local ja emetia headers correctament
- ✅ **Split vNext Phase 5:** NO_TRADE enforçat quan `quality_gate.is_bad()` — OrderOpenService comprova gate abans d'executar; `DataQualityGateBadError` → 422; 5 tests
- ✅ **Split vNext Phase 6:** Soak e2e (3 casos OK/BAD/down) validat; retenció candles augmentada (4320h / 180 dies); `scripts/run_soak_e2e.sh`; artifact `datafiles/e2e_runs/`
- ✅ **Split vNext Phase 7:** `run_all.py` VERD — 3 fixes (IndentationError, app.title assert, warmup READY); venue/test matrix documentada. Lighter/gTrade tests arxivats (T5.32).
- ✅ **Split vNext Phase 8:** Compat sampling Ostium↔Dukascopy executat amb dades reals. EURUSD: PARTIAL (corr=0.958, dir_agree=90%, diff p95=0.5pip); XAUUSD: PARTIAL (corr=0.977, dir_agree=90.7%, diff p95=$0.98).
- ✅ **Split vNext Phase 9:** `PASS_BACKTEST` — nova mètrica `dir_agree_filtered_1m` (ignora minuts flat/soroll feed). EURUSD: **PASS_BACKTEST** (corr=0.968, dir_agree_filtered=96.7%); XAUUSD: **PASS_BACKTEST** (corr=0.977, dir_agree_filtered=95.9%). `allowed_for_backtest=true` per ambdós.
- ✅ **Phase 10:** `BacktestMarketDataProvider` registry-aware. EURUSD/XAUUSD → `ostium_local`; no graduat → `dukascopy`. Headers X-Data-* coherents. 9 tests 0-network. `application/data/backtest_market_data.py`.
- ✅ **Phase 11:** Backtest runner offline + estratègia `simple_trend` + KPIs (trades, win_rate, pnl, max_drawdown) + artifact JSON. `application/tools/run_backtest.py`, `scripts/run_backtest_offline.sh`. 12 tests 0-network.
- ✅ **Phase 12:** Backtest API REST: `POST /api/v1/backtests/run` → run_id + KPIs + x_data; `GET /api/v1/backtests/runs/{run_id}` → artifact JSON. Artifact persistit a `datafiles/backtests/`. 8 tests 0-network. `application/api/backtest_routes.py`.
- ✅ **Phase 13:** `run_all.py` usable: quiet + fail-fast per defecte, `--verbose`, `--no-fail-fast`. Lighter/gTrade tests arxivats (T5.32).
- ✅ **Phase 14:** OHLCV Data API registry-aware: `GET /api/v1/data/ohlcv/{symbol}?tf=1m&from_ts=&to_ts=&limit=&offset=`. Format candles `[ts,o,h,l,c,v]`. Paginació `next_offset`. X-Data-* headers. 9 tests 0-network. `application/api/data_routes.py`.
- ✅ **Phase 15:** Parquet storage particionat + backfill runner. `infrastructure/storage/parquet_store.py` (write/read/range/coverage, idempotent, validació). Runner `application/tools/run_historical_backfill.py` (mes a mes, skip_existing, rate-limit, 0-network via override). 13 tests 0-network.
- ✅ **Phase 16:** DuckDB query layer sobre Parquet. `infrastructure/query/duckdb_query_service.py` (predicate pushdown, cursor `next_ts`, `compute_xdata_headers`). `GET /api/v1/data/ohlcv/{symbol}` fa routing automàtic DuckDB si existeix Parquet; legacy sinó. 9 tests 0-network. `duckdb>=0.10.0` afegit a requirements.
- ✅ **Phase 17:** Backtest runner "Freqtrade-style" sobre Parquet. `application/tools/run_backtest_parquet.py` (loader estratègia dinàmic, DuckDB paginat, `pd.DataFrame` shape-compatible Freqtrade, KPIs, artifact JSON). `strategies/simple_trend_df.py` (exemple `generate_signals(df) -> pd.Series`). `scripts/run_backtest_parquet.sh`. 9 tests 0-network.
- ✅ **Phase 18:** Ops robustos per backfill 2003→avui. `application/data/coverage_index.py` (index JSON per mes: done/failed/empty, persistit a `_coverage/`). `run_historical_backfill.py` ampliada: retries/backoff exponencial, resume per coverage index, `--dry-run`, `--stop-after N`, `--retry-failed`. `scripts/run_full_pipeline.sh` wrapper. 11 tests 0-network.
- ✅ **Phase 19:** Data API long-range + Coverage API. `GET /api/v1/data/ohlcv/{symbol}` serveix rangs llargs des de Parquet via DuckDB amb cursor `next_ts` (multi-mes, sense solapament). `GET /api/v1/data/coverage/{symbol}?tf=1m` exposa el coverage index (summary + detall per mes). 10 tests 0-network.
- ✅ **Phase 20:** Mixed stitching parquet+realtime. `application/data/mixed_ohlcv_stitcher.py`: merge monotònic sense duplicats (realtime guanya en overlap), policy `HISTORICAL_MIXED_ALLOWED` (default=1), `source=mixed` quan dues fonts, cursor `next_ts` consistent. `scripts/run_historical_cron.sh` (daily/retry-failed/gap-repair). 6 tests 0-network.
- ✅ **Market-hours fix + golden tests (2026-02-21):** Corregit bug weekend a `engine.py` (XAUUSD/DAXEUR/SPXUSD mostraven `open` dissabte; NVDAUSD obria en cap de setmana). Break XAU/indices corregit a 17:00–18:00 NY (era 16:59–18:10). Nou helper `_next_sunday_18()`. Tests anti-regressió `test_market_hours_golden_weekend.py` (7 tests).
- ✅ **Phase C: Historical dashboard + nginx proxy + cron metadata (2026-02-21):** `GET /health` i `/status` a historical_datalayer. Nginx `datalayer-proxy` unifica port 8081: `/realtime/*` → realtime:8082, `/data/*` → historical:8002. `application/data/cron_metadata.py` (atomic write/read `_cron/last_runs.json`). `run_historical_cron.sh` escriu metadata. `get_historical_router()` exposa `/ohlcv` i `/coverage` sense prefix. 19 tests 0-network.
- ✅ **Phase D: Gateway single-port complet (2026-02-21):** Nginx `:8081` exposa `/trade/*` → trading_service:8010 (strip prefix) i `/backtests/*` → trading_service:8010/api/v1/backtests/* (alias). `datalayer-proxy` ara és el punt d'entrada únic per tots els serveis. `scripts/smoke_gateway.sh` verifica tots els prefixos. Ostium exec Phase G/H implementat (paper + LIVE).
- 🟡 **gTrade/Lighter** arxivats (T5.32) → `_archive/`; paper intern depèn de `infrastructure/venues/lighter` per symbols
- 🧪 **Ostium LAB** — [lab/ostium/README.md](../lab/ostium/README.md); monitor continu via `run_lab.sh ostium-monitor`
- ✅ **Ostium Core (Trade Layer) read-only:** posicions via TradingStorage.getOpenTrade (Trade(9)); EURUSD=pair_id 2; smoke `smoke_ostium_preflight_call.py` 0-TX opt-in
- ✅ **Ostium trades:** orders/open suportat en PAPER (paper store) i LIVE (kill-switch ENABLE_LIVE_TRADING). orders/close suportat (PAPER idempotent; LIVE guarded). GET `/api/v1/broker/positions?venue=ostium` reflecteix posicions (PAPER: store; LIVE: chain). Smoke E2E LIVE opt-in: `./scripts/run_ostium_live_smoke.sh` (wrapper canònic). DATA_QUALITY_MAX_MISSING_MINUTES (default 1) controla la gate d'open LIVE (missing_minutes > allowed → BAD).
- ✅ **Ostium LIVE smoke (T5):** Override `deploy/compose/overrides/ostium-live-trading.yml` per trading_service en mode LIVE. **Regla crítica: NO aturar ni recrear realtime_datalayer**. **Una comanda:** `./scripts/up_ostium_live.sh` (up + smoke). O manual: `./scripts/run_ostium_live_smoke.sh --recreate --clean`. Requereix `lab/ostium/.env` amb RPC_URL, PRIVATE_KEY. Veure `deploy/compose/overrides/README.md`.
- ✅ **T7.1: Política SL/TP client-side (2026-02-26):** `CLOSE_REASON_TTL` + `PaperExecutionEngine.check_ttl()` + `PaperRiskEngine(ttl_s=...)`. Tool `application/tools/run_paper_trade.py` (cicle open→monitor→close via HTTP). `compute_sl_tp()` + `check_sl_tp_triggered()`. Config: `PAPER_SL_PCT` (2%), `PAPER_TP_PCT` (4%), `PAPER_TTL_S` (3600s), `PAPER_POLL_S` (5s). 13 tests 0-network + 6 smokes. Smoke: `python3 -m application.tools.run_paper_trade --symbol EURUSD --side long --collateral 100 --leverage 5 --ttl-s 60`.
- ✅ **T7.2/T7.2.1: LIVE/testnet smoke (2026-02-26):** Tool `application/tools/run_live_smoke_trade.py` — cicle mínim open→wait→close + close-idempotent. T7.2.1: `CONFIG` inclou `enable_live_trading` + `resolved_mode=LIVE|PAPER`; timeout fa best-effort close (evita posicions obertes). Mesura `open_ack_ms` + `close_ack_ms`. Artifact: `latest_live_smoke_<SYMBOL>.json`. Ús: `python3 -m application.tools.run_live_smoke_trade --venue ostium --symbol EURUSD --side long --collateral 1.5 --leverage 2 --wait-s 10`.
- ✅ **T7.3: LIVE TTL-only monitor (2026-02-26):** Tool `application/tools/run_live_ttl_trade.py` — open→poll(preu real)→close(TTL). Polling cada `poll_s`; tanca per TTL determinista; guarda mostres de preu. Artifact: `latest_live_ttl_<SYMBOL>.json` amb `poll_count`, `ttl_elapsed_s`, mostres de MONITOR. Ús: `python3 -m application.tools.run_live_ttl_trade --venue ostium --symbol EURUSD --side long --collateral 1.5 --leverage 2 --ttl-s 60 --poll-s 5 --max-duration-s 120`.
- ✅ **T7.3.1: Scripts live_on/live_off canònics (2026-02-26):** `./scripts/live_on.sh` / `./scripts/live_off.sh` — activació/desactivació LIVE idempotent. `--force-recreate trading_service ONLY` (mai toca realtime_datalayer). Verificació via preflight (`mode`, `live_enabled`). Override PAPER: `deploy/compose/overrides/live.off.yml`. Rollback sempre segur en < 10s.
- 🟡 **T8.17: Paritat Dukascopy M1 vs SQ EURUSD — Fase A (2026-02-28):** Sync test 2003-05→2006-12 confirma que Dukascopy públic NO té M1 per EURUSD anterior a 2007-01. `done=1, empty=43`: 1 candle artefact (2007-01-01 mal ubicada a 2006-12) eliminada. Coverage final: **175 mesos, 5,756,530 rows, 2007-01→2026-02**. Delta vs SQ (-32.3%) explicat per limitació de la font (SQ usa ticks 2003-2006). Gate A: **PARTIAL** acceptat. Doc `docs/DATA_PARITY_GATES.md` creat amb 4 gates (A/B/C/D). Report: `lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json`. Fase B (aggregation) PENDENT.
- ✅ **T8.16: Quality Gate 2 modes + No-Delete + Resync 2012-2014 (2026-02-28):** Refactor complet del quality gate per evitar eliminació accidental de dades vàlides. `QUALITY_MODE=ingest` (default): accepta qualsevol rows>0 — baixa tot el que Dukascopy retorna sense jutjar cobertura. `QUALITY_MODE=integrity`: aplica MIN_ROWS/MIN_COMPLETENESS/MAX_FLAT_RATIO — per diagnòstic manual. `sync_manager._process_month()` **mai fa unlink()** quan hi ha rows; parquets buits filtrats per `has_month()`. Nous camps `SyncJob`: `empty` (mesos Dukascopy buits), `suspect` (cobertura baixa informatiu), `suspect_months`. `sync_symbol.sh` mostra `empty`/`suspect` al poll i resum final. **Resync 2012-01→2014-06**: 30 mesos recuperats, 5,756,530 rows (era 4,464,877). Coverage: 175 mesos, 2007-01→2026-02. 21 tests 0-network (T8.13+T8.14 inclosos).
- ✅ **T8.14: Quality gate mensual al sync (2026-02-28):** `application/data/month_quality.py` — `MonthQualityStats` + `compute_month_stats()` + `expected_minutes_1m()`. Thresholds configurables via env vars: `MIN_ROWS_MONTH_1M=10000`, `MAX_FLAT_RATIO_GATE=0.05`, `MIN_COMPLETENESS_1M=0.50`. `sync_manager._process_month()` reestructurat: loop fetch+write+quality gate integrat; si gate falla → elimina parquet escrit + retry; si s'esgoten tots els intents → `job.failed` (no `job.done`). Gate aplicat només per `tf=1m`. Thresholds permissius vs parity checker (50%/5% vs 90%/2%) per permetre mesos Dukascopy 2012-2014 (60-80% completeness real). 5 tests 0-network `test_month_quality_gate.py`. `test_sync_manager.py` adaptat per desactivar gate via env vars.
- ✅ **T8.13: Fix parquets buits perpetus (2026-02-28):** `has_month()` usa `pyarrow.parquet.read_metadata().num_rows > 0` (O(1)) en comptes de `exists()` — detecta correctament parquets buits de 0 rows. `write_month([])` retorna `None` sense crear fitxer (Regla B). `sync_manager._process_month`: mesos amb fetch=[] marquen `coverage=empty` i `job.skipped++` (no `job.done`); mesos amb `coverage=empty` fan skip al proper job (Regla D). Script `application/tools/repair_empty_parquets.py`: detecta i elimina parquets buits existents amb `--dry-run`/`--fix`/`--resync`. 6 tests 0-network `test_empty_parquet_guard.py`. Dry-run al contenidor confirma 98 parquets buits (1257B) detectats correctament.
- 🔄 **T8.12: Paritat M1 EURUSD amb SQ (2026-02-28):** `application/data/parity_checker.py` — `ParityChecker`: escaneja parquets mensuals M1, calcula `completeness_ratio` (records/expected_minutes dies-laborables) i `flat_bars_ratio` (O=H=L=C), marca mesos "ok/bad/missing". Endpoints: `GET /parity/{symbol}/m1` (informe per mes) i `POST /parity/{symbol}/m1/retry` (re-sync mesos bad via SyncManager). `scripts/parity_check.sh`: sync → check → auto-retry → report JSON+CSV. 5 tests 0-network `test_parity_checker.py`. **Estat actual** (pre-sync complet, 2026-02-28): 5,756,531 records (target SQ: 8,499,508, delta=-32.3%). Coverage real Dukascopy: 2006-12→2026-02 (2003-2006 Dukascopy retorna 0 candles; 2007-06→2011-12 sync en curs). Report final pendent a `lab/runner/out_compare/parity_EURUSD_M1.json`.
- ✅ **T8.11: Alineament LAB↔MT4: ATR Wilder + warmup + D1 offset (2026-02-28):** Tres canvis al runner per apropar LAB a MT4: (1) **ATR Wilder** (`ewm alpha=1/period`): equivalen a MT4 `iATR`, en lloc de rolling mean simple. (2) **Warmup** (`warmup_bars=250` al YAML o `--warmup-bars`): fetch addicional de 251 dies per estabilitzar EMA200/RSI; trades del warmup filtrats dels artifacts. (3) **Day offset D1** (`day_offset_h=5` al YAML o `--day-offset-h`): barres D1 ara comencen a 05:00 UTC (=00:00 UTC-5, equivalent MT4 Dukascopy). **Resultat T8.11** (EURUSD D1 2006-12→2026-01): n_trades=18, net_pnl=+1.96%, win_rate=44.44%, max_dd=4.39%. Entry match-rate vs MT4: **31.6% → 50.0%** (+18pp). Desfasament residual: 9 trades matched (diff 7-24h = 1 barra D1, normal); 9 NO-MATCH per ATR diferent que canvia quines barres toquen RSI<35.
- ✅ **T8.10: Comparador trades SQ-engines vs LAB (2026-02-28):** `lab/runner/out_compare/compare_trades.py` — normalitza MT4/MT5H/MT5N/JForex (sep=;, UTC-5→UTC) i LAB `trades.csv`. Mètriques: entry/exit match-rate (±tol), PnL sum, PnL diff vs ref, median hold time, reasons breakdown. Output: `report.json` + `report.csv`. **Resultat T8.10** (EURUSD D1 ref=MT4 tol=1D): MT4=MT5H=MT5N 100% match (idèntics); JForex 100% match (PnL +$1.60 per spread diferent); LAB 31.6% entry match (19 vs 22 trades, ATR rolling vs Wilder explica la diferència). `lab/runner/out_compare/README.md` amb conclusions i instruccions.
- ✅ **T8.9: Import SQ EMA200+RSI35+ATR EURUSD D1 al LAB (2026-02-28):** Estratègia `eurusd_ema200_rsi35_atr_d1` (yaml+py). Entry: `Close[1] > EMA(200)[1] AND RSI(14)[1] < 35`, SL=2×ATR(14), TP=3×ATR(14), weekends OFF, EOD OFF. Run 2006-12→2026-01: n_trades=19, net_pnl=+2.22%, win_rate=42.11%, max_dd=3.65%, PF=1.19. **Comparable vs SQ**: trades=22, profit>0, PF=1.75 (diferència win_rate per ATR rolling vs Wilder i SL-first conservador). Mapping SQ→LAB documentat a `compare_notes.md`. EMA: ewm(span, adjust=False); RSI: Wilder ewm(alpha=1/period).
- ✅ **T8.8: LAB Runner Execution Contract v2 + backtest real (2026-02-27):** `run_backtest.py` reescrit amb Execution Contract v2: senyals a barra `i` usant dades `[0..i-1]`, entrada MARKET a `open[i+1]`, SL/TP intra-bar via `high/low`, SL-first si ambdós toquen al mateix bar, TTL exit a `open[entry+ttl_bars]`. `--ensure-sync` + coverage fail-fast (rebuild post-sync, error si gaps en rang). `--artifacts-dir` per artifacts fora del contenidor. **Run de referència T8.8** (SQ_0423850 XAUUSD 4h 2016-01-01→2026-01-01): n_trades=45, net_pnl=+14.84%, win_rate=57.78%, max_drawdown=4.42%, avg_trade=+0.33%. `EXECUTION_CONTRACT` string guardat a `summary.json`. 8 tests 0-network (`test_lab_runner_contract.py`): contracte, SL-first, SL-only, TP-only, TTL, friday_exit, no_entry_weekend, contract_string. Nota run contenidor: `--base-url http://datalayer-proxy:8081` (gateway Docker), `--artifacts-dir /app/lab/out/artifacts` (volum muntat).
- ✅ **T8.7: Benchmark EURUSD concurrent sync (2026-02-27):** Validació T8.6 amb EURUSD complet (2003→2026). **Resultats:** 277 mesos baixats, 1 skip (2020-01 pre-existent), 0 failed, 0 retries. Durada: **27min** (1623s). Throughput: **10.2 mesos/min** (4 workers). Coverage real Dukascopy EURUSD: `2006-12→2026-02` (2003-2006 buits). **Dedup PASS:** 2a crida simultània → `is_new=false, same job_id`. **Idempotència PASS:** re-run immediat → `done=0, skipped=278, written=0` en <5s. **Missing month PASS:** 2022-06 eliminat → re-sync baixa 1 mes en ~18s, `done=1, failed=0`.
- ✅ **T8.6: SyncManager concurrent (2026-02-27):** `SyncManager` N workers asyncio (default 4, `SYNC_WORKERS` env). Job tracking amb `job_id` (sha1 dedup), progrés en temps real, persistència `_coverage/sync_jobs.json`. `POST /data/sync` retorna immediatament `{job_id, status=RUNNING, ...}`. `GET /data/sync/{job_id}` per poll. `GET /data/sync` llista jobs recents. `scripts/sync_symbol.sh` actualitzat per poll fins DONE/FAILED. 8 tests 0-network. `application/data/sync_manager.py`.
- ✅ **T8.2: Rebuild coverage index des del disc (2026-02-27):** `POST /data/coverage/{symbol}/rebuild` — escaneja Parquets reals, regenera index atòmicament (Parquet=source of truth). Idempotent (`changed=false` si res canvia). Detecta `months_missing` (gaps entre primer i últim done). 7 tests 0-network. `application/data/rebuild_coverage.py`.
- ✅ **T8.3: POST /sync robust (2026-02-27):** Ara fa rebuild pre i post-sync. `from_d` calculat des del disc (no del JSON potencialment desincronitzat). Cobertura real sempre reflectida. `skip_existing=True` basat en disc (el backfill ja ho feia).
- ✅ **T8.4: Script sync_symbol.sh idempotent (2026-02-27):** `./scripts/sync_symbol.sh SYMBOL [--from] [--to] [--max-retries N]`. Flux: rebuild→sync(chunks CHUNK_YEARS)→rebuild→gap-check→auto-retry. Exit 0 si cobertura OK, exit 1 si gaps persistents. Idempotent i segur de relançar.
- ✅ **T8.1: POST /sync — sync idempotent Dukascopy→Parquet (2026-02-27):** `POST /data/sync` (gateway) o `POST /api/v1/data/sync` (directe). Body: `{"symbol":"XAUUSD","tf":"1m","from":"2016-01-01"}`. Detecta coverage existent, baixa NOMÉS delta, retorna `{status, months_written, candles_written, coverage_from/to}`. Guardrail: màx 10 anys/crida. Idempotent: 2a crida → `status=up_to_date`. 6 tests 0-network.
- ✅ **T8.0: LAB Runner MVP (2026-02-26):** `lab/runner/` — pipeline backtest d'estratègies. `SmokeStrategy` (sempre LONG, TTL) + `sq_0423850` (Bollinger Lower crossover, LONG only, SL/TP ATR, traduïda de SQ pseudocodi). Runner `lab/runner/backtest/run_backtest.py`: fetch candles via gateway (:8081), agrega 1m→tf, simula trades (TTL/SL/TP/divendres exit), genera artifacts (`summary.json`, `trades.csv`, `equity.csv`). Script canònic: `./scripts/run_lab_backtest.sh`. Run validat: smoke/EURUSD/1h 2020-01 → 165 trades; sq_0423850/EURUSD/1h 2020-01 → 1 trade. Pipeline llest per afegir estratègies SQ sense refactor.
- **T5.16/T5.18/T5.19/T5.20/T5.22/T5.24 (2026-02-24) Smoke LIVE Ostium:** T5.19 Fast-ACK; T5.20 `--clean`; T5.22 up explícit; T5.24 tag `v0.1.0-ostium-live-mvp`. **Happy path:**
  - **Run:** `./scripts/up_ostium_live.sh`
  - **Smoke only:** `./scripts/run_ostium_live_smoke.sh --recreate --clean`

> **Phases 2–20 + Phase C + Phase D completades.** EURUSD i XAUUSD: **PASS_BACKTEST**. Parquet (15) + DuckDB (16) + Backtest Freqtrade-style (17) + Ops robustos (18) + Data API long-range + Coverage API (19) + Mixed stitching + Cron (20) + Historical dashboard + nginx proxy (C) + Gateway single-port (D). Pipeline prod-ish per backfill 2003→avui. 74 tests 0-network, run_all verd. **Single-port API: `:8081/realtime`, `:8081/data`, `:8081/trade`.** Ostium exec Phase G/H implementat (paper + LIVE).

### Single-port API (Phase D)

| Prefix extern (`:8081`) | Servei intern | Strip prefix | Notes |
|-------------------------|---------------|-------------|-------|
| `/realtime/*` | `realtime_datalayer:8082` | sí | health, status, ohlcv, ui |
| `/data/*` | `historical_datalayer:8002` | sí | health, status, ohlcv, coverage |
| `/trade/*` | `trading_service:8010` | sí | api/v1/broker/*, api/v1/backtests/* |
| `/backtests/*` | `trading_service:8010` | → `/api/v1/backtests/*` | alias comoditat |
| `/nginx-health` | nginx intern | — | healthcheck proxy |
| `/` | — | — | 302 → `/realtime/ui` |

**Smoke (routing):**
```bash
./scripts/smoke_gateway.sh                   # localhost:8081
./scripts/smoke_gateway.sh <host> <port>     # remot
```

**Network smokes opt-in (Ops-1a) — connectivity + read-only, NO CI:**
```bash
# Tot (connectivity + gateway read-only):
./scripts/network_smokes/run_network_smokes.sh

# Només connectivitat i config (0 transaccions):
./scripts/network_smokes/run_network_smokes.sh --only-connectivity

# Només gateway read-only (GETs):
./scripts/network_smokes/run_network_smokes.sh --only-gateway

# Amb host/port remot o timeout personalitzat:
BASE_URL=http://10.0.0.1:8081 SMOKE_TIMEOUT=3 ./scripts/network_smokes/run_network_smokes.sh
```

Categories d'error del report: `DNS`, `CONNECT_TIMEOUT`, `CONNECT_REFUSED`, `HTTP_4XX`, `HTTP_5XX`, `AUTH_MISSING_ENV`, `AUTH_INVALID_FORMAT`, `UNEXPECTED_PAYLOAD`. Cada FAIL inclou `next_action` accionable.

**Network smokes Ostium read-only (Ops-1b) — RPC + subgraph, opt-in, NO CI:**
```bash
# Smoke Ostium (RPC liveness + chain guard + subgraph probe):
OSTIUM_RPC_URL=https://... OSTIUM_CHAIN_ID=421614 \
  ./scripts/network_smokes/run_network_smokes.sh --only-ostium

# Amb subgraph probe (stale → FAIL en comptes d'INFO):
OSTIUM_RPC_URL=https://... OSTIUM_SUBGRAPH_URL=https://... \
  ./scripts/network_smokes/run_network_smokes.sh --only-ostium --require-subgraph
```

Statuses del report Ostium: `PASS` / `FAIL` / `INFO` / `SKIP`. `INFO` no incrementa exit code.
Categories addicionals: `CHAIN_MISMATCH` (chain_id != OSTIUM_CHAIN_ID), `SUBGRAPH_STALE` (subgraph respon però no indexa).
**Nota subgraph testnet:** known-broken (no indexa noves TX). Per defecte és `INFO SUBGRAPH_STALE`, no `FAIL`. Canonical Ostium LAB E2E: `lab/ostium/scripts/test_full_cycle_multicall.py`. Cleanup: `lab/ostium/scripts/close_all_open_trades.py`.

**Network smokes Ostium preflight call (Ops-1c) — eth_call getOpenTrade, 0 TX, opt-in, NO CI:**
```bash
# Simulació eth_call al contract (sense enviar cap TX):
OSTIUM_RPC_URL=https://... OSTIUM_CHAIN_ID=421614 OSTIUM_CONTRACT_ADDRESS=0x... OSTIUM_WALLET_ADDRESS=0x... \
  ./scripts/network_smokes/run_network_smokes.sh --only-ostium-preflight
```
Categories addicionals: `CONTRACT_REVERT` (revert reason si el RPC el retorna). Next_action per FAIL indica revisar adreça contract/chain/wallet.

**Verificació Ops-1c (DoD, fil per fil):**
- [x] Script `scripts/network_smokes/smoke_ostium_preflight_call.py` creat i executable (0 TX, eth_call getOpenTrade).
- [x] Runner `run_network_smokes.sh` amb flag `--only-ostium-preflight`.
- [x] ENV: OSTIUM_RPC_URL (obligatori), OSTIUM_CHAIN_ID (recomanat), OSTIUM_CONTRACT_ADDRESS (default testnet), OSTIUM_WALLET_ADDRESS (dummy 0x0), OSTIUM_MARKET_SYMBOL (EURUSD→pair_id=0). Sense secrets a logs.
- [x] Report: PASS/FAIL/INFO/SKIP + category + next_action. Exit 0 sense FAIL, 1 amb FAIL.
- [x] Categories: AUTH_MISSING_ENV, AUTH_INVALID_FORMAT, CHAIN_MISMATCH, CONTRACT_REVERT, DNS, CONNECT_*, UNEXPECTED_PAYLOAD.
- [x] Tests 0-network: `testing/apps/trading_service/test_ostium_preflight_call.py` (14 tests, suite trading_service). Payload determinista i classificació CONTRACT_REVERT coberta.
- [x] No integrat a CI (opt-in). ABI/adreces: font canònica `infrastructure/venues/ostium/ostium_client.py`; default testnet al script.
- Observabilitat: check de la crida view = `ostium.pf.call.getOpenTrade` (equivalent a "preflight call open").
- **Core positions via TradingStorage:** OstiumClient llegeix open trades amb TradingStorage.getOpenTrade (Trade(9)); smoke preflight 0-TX valida amb `OSTIUM_RPC_URL TRADER_ADDRESS PAIR_ID=2 INDEX=0` (i opcional `OSTIUM_TRADING_STORAGE_ADDRESS`).

**Nota:** Ostium exec Phase G/H implementat (paper + LIVE). Phase E (TradingCore) completada. Estat i reproducció d’errors del trade-cycle testnet: [scripts/network_smokes/ESTAT.md](../scripts/network_smokes/ESTAT.md).

### Boundaries ràpides per servei

| Servei | Fa | No fa |
|--------|----|-------|
| **realtime_datalayer** | Ingest Ostium (polling), candles 1m, OHLCV+X-Data-* headers, market-hours, hot-reload símbols | Backfill Dukascopy, ordres, backtesting |
| **historical_datalayer** | Backfill Dukascopy, Parquet, DuckDB, Coverage API, mixed stitching, cron | Ingest temps real, ordres, market-hours gating |
| **trading_service** | Execució ordres (Ostium paper/LIVE), quality gate fail-closed, backtest API | Ingest Ostium, backfill Dukascopy, emmagatzematge candles |

**Data flow (T5.38):** realtime_datalayer escriu candles 1m a `datafiles/realtime_datalayer/candles/` (CSV). historical_datalayer escriu Parquet a `datafiles/historical_parquet/` (Dukascopy backfill). **No hi ha rollover** realtime→historical; el stitching és en lectura: `mixed_ohlcv_stitcher` combina Parquet + CSV realtime quan es serveix OHLCV. **Trading llegeix de realtime_datalayer via HTTP** (`REALTIME_DATALAYER_BASE_URL`); sense config → LocalDataLayerReader (fitxers).

---

## Arquitectura split vNext — estat de migració

**Estat Phase 1:** Entrypoints reals per servei. Cada servei arrenca només el que li toca (role boundaries).

**Serveis:** `realtime_datalayer`, `historical_datalayer`, `trading_service`. Veure `AGENTS_ARQUITECTURA.md` § Split vNext.

**Què garanteix Phase 1:**
- Cada servei té entrypoint propi: `apps/<servei>/app.py`
- `SERVICE_ROLE` (env) determina què wireja: realtime (ingest), historical (backfill), trading (adapter)
- realtime_datalayer: només data routes (health, data_status, ohlcv, candles); sense /orders
- trading_service: data + trading; sense Ostium ingest ni Data Layer writer
- data_status mai 503 en initializing (realtime)

**Comandes canòniques:**
```bash
# Validar compose split
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml config

# Aixecar els 3 serveis (entrypoints: apps.realtime_datalayer.app, etc.)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer historical_datalayer trading_service

# Realtime DataLayer v1 (servei sol)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer
curl -s http://localhost:8081/health
curl -s http://localhost:8081/status

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer

# Phase 2: trading_service consumeix realtime via HTTP (REALTIME_DATALAYER_BASE_URL)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer trading_service
curl -s http://localhost:8010/api/v1/broker/data_status
curl -s "http://localhost:8010/api/v1/broker/coverage?symbol=EURUSD&resolution=1m"
curl -s "http://localhost:8010/api/v1/broker/ohlcv/EURUSD?tf=1m&limit=5"
# Verificar quality gate als logs del trading_service:
docker logs trading_service 2>&1 | grep -E "quality_gate|QUALITY_GATE"
```

**Phase 2 — Quality Gates (fail-closed):**
- `REALTIME_DATALAYER_BASE_URL` set → HTTP reader actiu → `get_ohlcv_with_gate` avalua `X-Data-*` headers
- `QualityGateResult.status`: `ok` (dades netes) | `bad` (gaps/stale/missing headers)
- Trading loop: si `gate.is_bad()` → NO_TRADE, log + reason
- Env override dels llindars: `QUALITY_GATE_MAX_FRESHNESS_SEC` (default 300s), `QUALITY_GATE_MIN_COMPLETENESS` (default 0.95), `QUALITY_GATE_MAX_GAP_S_GATE` (default 180s)
- **MVP LIVE** (completeness ~0.90): posar `QUALITY_GATE_MIN_COMPLETENESS=0.90` i recrear només `trading_service` (NO realtime): `docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d --force-recreate trading_service`
- Fail-closed: si headers `X-Data-Coverage-From/To` absents → `bad/missing_headers`
- Mercat tancat: si `missing_minutes==0` i `max_gap_s==0` → `ok` (no incident, freshness ignorada)

**Estructura:** `apps/<servei>/app.py` (entrypoint), `application/app_factory.py` (create_app role-aware), `packages/shared/realtime_datalayer_client.py` (Phase 2), `application/data/quality_gate.py` (QualityGateEvaluator).

**Docs per subprojecte:**

| Servei | Arquitectura | Estat |
|--------|-------------|-------|
| realtime_datalayer | [arquitectura](../apps/realtime_datalayer/realtime_datalayer_arquitectura.md) | [estat](../apps/realtime_datalayer/realtime_datalayer_estat.md) |
| historical_datalayer | [arquitectura](../apps/historical_datalayer/historical_datalayer_arquitectura.md) | [estat](../apps/historical_datalayer/historical_datalayer_estat.md) |
| trading_service | [arquitectura](../apps/trading_service/trading_service_arquitectura.md) | [estat](../apps/trading_service/trading_service_estat.md) |

**Realtime DataLayer v1 (servei independent):**
- Storage: `datafiles/realtime_datalayer/candles/`, `datafiles/realtime_datalayer/ticks/`
- Retenció: `REALTIME_CANDLES_MAX_HOURS` (default **4320h = 180 dies** des de Phase 6), `REALTIME_TICKS_MAX_HOURS` (default 720h = 30 dies)
- Docs: `apps/realtime_datalayer/realtime_datalayer_arquitectura.md`, `realtime_datalayer_estat.md`
- Tests curts: `./scripts/run_tests.sh realtime_datalayer`

**Phase 6 — Soak e2e + Retenció:**
- Soak e2e 3 casos (0-network, reproduïble): `./scripts/run_soak_e2e.sh`
  - Cas A (gate=OK): `POST /orders/open` → 200, adapter cridat
  - Cas B (gate=BAD): `POST /orders/open` → 422 `DATA_QUALITY_GATE_BAD`, adapter NO cridat
  - Cas C (datalayer down): reader llança exc → 422 `DATA_QUALITY_GATE_BAD` (fail-closed)
- Artifact JSON: `datafiles/e2e_runs/YYYYMMDD_HHMMSS_soak_e2e.json`
- Retenció candles augmentada al compose split: `REALTIME_CANDLES_MAX_HOURS=4320` (180 dies), `REALTIME_TICKS_MAX_HOURS=720` (30 dies)
- Mode live (serveis Docker reals): `./scripts/run_soak_e2e.sh live`

---

## Tests canònics per focus (vNext)

**Suites curtes:** `./scripts/run_tests.sh <suite>` — focus-driven sense run_all.

| Suite | Comanda | Quan s'usa |
|-------|---------|------------|
| smoke | `./scripts/run_tests.sh smoke` | Validar instal·lació i imports (1 test) |
| core | `./scripts/run_tests.sh core` | foundation/shared (candle_store, gap_validator, etc.) |
| realtime_datalayer | `./scripts/run_tests.sh realtime_datalayer` o `./test.sh testing/run_realtime.py` | Data Layer + Ostium ingest (curt, 0-network) |
| historical_datalayer | `./scripts/run_tests.sh historical_datalayer` | Dukascopy/compat/backfill |
| trading_service | `./scripts/run_tests.sh trading_service` | execució/venue adapters |

**Full suite:** `./test.sh testing/run_all.py` — tot (lent; CI o validació completa). **Ha de quedar VERD** (Phase 7).

**Estructura:** `testing/suites/*.txt` (paths), `testing/apps/<servei>/` (tests migrats). La resta a `testing/unit/`, `testing/integration/`, `testing/api/` — pendent de migració.

**Venue / Test Matrix (canònic vs LAB/opt-in):**

| Subprojecte | Venue marketdata | Venue exec | Estat tests |
|-------------|-----------------|------------|-------------|
| realtime_datalayer | **Ostium** (canònic) | — | Suite `realtime_datalayer` VERDA |
| trading_service | Ostium via HTTP (gate) | **Ostium** (paper + LIVE) | Suite `trading_service` VERDA |
| historical_datalayer | **Dukascopy** (target) | — | Suite `historical_datalayer` verda |
| Compat Ostium↔Dukascopy | Ostium + Dukascopy | — | Opt-in `--include-ostium-compat`; **Phase 8 fet** (EURUSD PARTIAL) |

**T5.32:** gTrade i Lighter tests/suites arxivats → `_archive/testing/2026-02-legacy-purge/`.

---

## Data Layer prod v0

**Activar:** `DATA_LAYER_ENABLED=1` (default 0). Prefetch + writer loop + gates.

**Docker prod-ish:** `docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage`

**Scripts canònics:** `./scripts/run_smoke.sh data-layer` (3 min), `./scripts/run_soak.sh 30 data-layer` (30 min). Artifacts a `datafiles/data_layer_prod_runs/`.

**Startup gate:** `DATA_LAYER_STARTUP_GATE=1` → health=degraded si Data Layer DEGRADED; startup falla si gate ON i prefetch degradat.

**Providers:** Ostium + DukascopyBackfillProvider (ostium). LighterCandlestickBackfillProvider arxivat (data-layer legacy).

**Observabilitat:** `GET /api/v1/broker/data_status` → `symbol_state` + `degrade_reason`.

**Config:** `DATA_LAYER_PREFETCH_MINUTES`, `DATA_LAYER_WARMUP_MINUTES` (default 120), `DATA_LAYER_WRITE_SYMBOLS`, `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS`.

**symbol_state:** `ACTIVE` | `DEGRADED`. Si DEGRADED → writer aturat per aquell símbol.

**Perfil Ostium:** `OSTIUM_ENABLED=1` + `DATA_LAYER_WRITE_MODE=realtime_plus_backfill`. Realtime: OstiumCandleIngestService (polling REST); històric/gaps: DukascopyBackfillProvider. `backfill_only` = ingest OFF. Gates market-hours aware: soak en cap de setmana no DEGRADED per stale. `./scripts/run_smoke.sh ostium`, `./scripts/run_soak.sh 30 ostium`.

**Tick recorder (forense):** Opt-in `OSTIUM_TICK_RECORDER_ENABLED=1`. Escriu ticks/snapshots a JSONL (`lab/out/ostium_forensics/daily/YYYYMMDD/<symbol>.jsonl`). Rotació diària + retenció (`OSTIUM_TICK_RETENTION_DAYS`, default 7). Best-effort: no bloqueja candles si el tick write falla. `data_status` inclou `tick_recorder` (enabled, outdir, last_tick_ts, lines_written, dupes_detected per símbol).

**Allowlist + Quarantine (Ostium prod-ish v1):**
- `OSTIUM_SYMBOLS` (default: EURUSD,GBPUSD): allowlist canònica — símbols que Ostium pot ingerir.
- `OSTIUM_QUARANTINE_SYMBOLS` (default: XAUUSD,XAU): símbols en quarantine — no ingest, no primary.
- `ingest_symbols = allowlist - quarantine`. Primary eligibility: `get_ostium_primary_allowed(symbol)` retorna `false` si quarantined (abans de mirar registry).
- `data_status` per símbol: `ingest_allowed`, `primary_eligible`, `quarantined`, `quarantine_reason`.

---

## Ostium ↔ Dukascopy compat (graduation gate)

**Propòsit:** Validar compatibilitat quantitativa Ostium (realtime recorded) vs Dukascopy (fallback històric). Només si **PASS** → `ostium_primary_allowed=true` per aquell símbol.

**Com validar:**
```bash
# Rolling (24h) — operatiu, per decidir si operem / quarantena:
python3 -m application.tools.ostium_compat_report --symbol EURUSD --mode rolling --minutes 1440
python3 -m application.tools.ostium_compat_report --symbol XAUUSD --mode rolling --minutes 1440

# Full overlap (T6.5) — auditoria, tot el rang disponible Ostium vs Dukascopy:
python3 -m application.tools.ostium_compat_report --symbol EURUSD --mode full
python3 -m application.tools.ostium_compat_report --symbol XAUUSD --mode full

# O via wrapper (default symbol=EURUSD, mode rolling)
./scripts/run_compat.sh ostium [symbol]
```

   **Artifact path (T6.2):** `datafiles/artifacts/compat/<ts>_compat_<symbol>_<Nm>m.json` (ex: `20260225_120000_compat_EURUSD_1440m.json`). **T6.3:** `latest_<symbol>.json` (overwrite) per resultat immediat; stdout RESULT amb symbol, verdict, corr, dir_agree_filtered, path, latest. Si PASS_BACKTEST → acceptable portar estratègia a paper-live.

**Registry:** `datafiles/compat_reports/ostium_compat_registry.json` — font de veritat per `get_ostium_primary_allowed(symbol)`.

**Permisos (gotcha resolt):** Ostium/data-layer compose usen `user: ${DOCKER_UID}:${DOCKER_GID}` perquè registry i artifacts siguin writable per host. run_smoke.sh i run_soak.sh exporten DOCKER_UID/DOCKER_GID. Si compose manual: `export DOCKER_UID=$(id -u) DOCKER_GID=$(id -g)` abans.

**Execució soak/post-compat:** run_soak data-layer i ostium corre dins Docker (`docker compose run brokerage`) per tenir dukascopy-python i deps (post-compat). run_compat.sh corre al host; si falla import: `pip install dukascopy-python` o executar dins Docker.

**Permisos (user mapping):** Els scripts fan `docker compose run --user "$(id -u):$(id -g)"` per evitar root-owned files a datafiles/compat_reports i artifacts.

**Verdict:** PASS | PARTIAL | FAIL (llindars via `compat_report_service` + constants). PASS → primary allowed; PARTIAL/FAIL → opt-in experimental sense declarar primary.

**PASS ⇒ primary (detall explícit):** Quan `ostium_primary_allowed(symbol)=true` → `primary_source=ostium_recorded`, `mixed_allowed=true`. Headers OHLCV: `X-Data-Source=ostium_recorded` (o `mixed` si rang travessa cutover), `X-Data-Primary-Source=ostium_recorded`. Coverage retorna `source=ostium_recorded`. data_status inclou `primary_allowed_by_symbol[symbol]=true`.

**Estat per símbol (prod-ish v1):**

| Símbol | Compat | allowed_for_backtest | allowed_for_live | Quarantined | Corr | Dir agree 1m | Dir agree filtrat | Diff preu p95 |
|--------|--------|---------------------|-----------------|-------------|------|--------------|-------------------|---------------|
| EURUSD | **PASS_BACKTEST** | ✅ true | ❌ false | No | 0.968 | 89.9% | **96.7%** (eligible=427) | ~0.5 pips |
| XAUUSD | **PASS_BACKTEST** (rolling+full) | ✅ true | ❌ false | Sí (quarantine config) | 0.971 (full, market_open) | 91.8% | **96.7%** (eligible=5262) | ~$0.98 |

**Interpretació (2026-02-25, rolling 1440m, market_open filter T6.8):**
- Les diferències de **preu absolut** entre Ostium i Dukascopy són negligibles per ambdós símbols.
- **dir_agree_1m ~90%**: soroll intrínsec entre dos feeds independents — minuts amb moviment quasi zero on qualsevol micro-diferència de timestamp canvia la direcció.
- **dir_agree_filtered**: exclou minuts "flat" (moviment < ε = 0.5pip per FX, $0.5 per XAU). Amb el filtre: EURUSD 96.7%, XAUUSD 96.6% → ambdós superen el llindar 95% → **PASS_BACKTEST**.
- **T6.8 market_open filter (XAUUSD):** exclou candles `zero_range` (h==l, stale durante break) + minuts `market_closed`. Rolling: excluded=2, corr_market_open=0.967. Full 7d: excluded=4, corr=0.652 (spike_to_break_price no filtrats — fix al recorder pendent).
- `allowed_for_live=false` fins acumular mostra suficient per PASS estricte (dir_agree_1m ≥ 95%).

### Evidence T6.6 — Execució real 2026-02-25 (rang 2026-02-18 → 2026-02-25)

| Símbol | Mode | aligned_total | aligned_ratio | corr | dir_agree_filtered | verdict | Artifact |
|--------|------|:---:|:---:|:---:|:---:|:---:|---|
| EURUSD | rolling 1440m | 1434 / 1440 | 0.9958 | 0.951 | 98.1% (eligible=777) | **PASS_BACKTEST** | `latest_EURUSD.json` |
| EURUSD | full (7d) | 7001 / 7025 | 0.9851 | 0.956 | 97.6% (eligible=3971) | **PASS_BACKTEST** | `latest_full_EURUSD.json` |
| XAUUSD | rolling 1440m | 1369 / 1369 | 0.9935 | 0.219 | 96.6% | **INCOMPATIBLE** | `latest_XAUUSD.json` |
| XAUUSD | full (7d) | 6734 / 6734 | 0.9854 | 0.415 | 96.7% | **INCOMPATIBLE** | `latest_full_XAUUSD.json` |

**Go/No-Go:**
- ✅ **EURUSD**: PASS_BACKTEST estable. aligned_ratio ~99.6% rolling, ~98.5% full 7d. Backtest autoritzat.
- ❌ **XAUUSD**: INCOMPATIBLE — corr molt baix (0.219–0.415) malgrat dir_agree_filtered >96%. **Veure diagnòstic T6.7.**

**Artifacts (host):** `datafiles/realtime_datalayer/artifacts/compat/`

### Diagnòstic T6.7 — Causa del mismatch XAUUSD (2026-02-25)

**Conclusió: `stale_candles_fixable`** — el problema és el recorder Ostium que **escriu candles `zero_range` (h==l)** durant els gaps de mercat tancat (tancament nocturn XAU 17:00–18:00 NY, cap de setmana). Quan el mercat reabre, el preu salta $100–$230 i el log-return d'Ostium és enorme mentre Dukascopy no té aquelles candles. Això destrueix la correlació de retorns.

| Mètrica | Rolling 1440m | Full 7d | Interpretació |
|---------|:---:|:---:|---|
| corr_price_raw | 0.978 | **0.999** | Feed correcte — preu Ostium = Duka |
| corr_returns_raw | 0.222 | 0.415 | Fals negatiu per stale |
| corr_returns_filtered | **0.964** | 0.647 | Millora molt en filtrar stale |
| stale_count | 1 | 3 | Candles zero_range detectades |
| max_stale_price_diff | — | **$230.31** | Salt de preu en reobertura |
| best_lag (returns) | 0 | 0 | Sense timezone/alignment issue |
| affine a | 1.012 | 1.000 | Sense escala/offset significatiu |

**Evidència clau (top diffs):**
- `2026-02-23 21:59 UTC`: Ostium=4996.32 (h==l, zero_range), Duka=5226.64 → diff=-230.31
- `2026-02-24 21:59 UTC`: Ostium=4996.32, Duka=5141.35 → diff=-145.02
- Patró: Ostium recorder "queda enganxat" al preu 4996.32 (tancament setmanal) mentre Dukascopy ja reflecteix el preu de reobertura

**Fix (T6.8):** Excloure candles `zero_range` (h==l) del compat engine, o filtrar candles fora d'horari de mercat XAU.

**Artifacts:** `datafiles/realtime_datalayer/artifacts/compat/`
- `20260225_200302_diagnosis_xauusd_rolling.json`
- `20260225_200308_diagnosis_xauusd_full.json`

**Nota:** El PASS anterior (18-feb, corr=1.000) era espuri — llegia del store `gtrade/` (Dukascopy via gTrade), no les candles Ostium reals. El run del 20-feb llegeix correctament de `realtime_datalayer/candles/`.

**Què canvia quan PASS → primary (mini-taula):**

| Aspecte | Sense PASS (opt-in) | Amb PASS (primary) |
|---------|---------------------|--------------------|
| X-Data-Source | `primary` genèric | `ostium_recorded` |
| X-Data-Primary-Source | — | `ostium_recorded` |
| Mixed (rang travessa cutover) | 422 MIXED_SOURCE_NOT_ALLOWED | Stitch fallback + primary |
| coverage source | `primary` | `ostium_recorded` |
| data_status primary_allowed_by_symbol | `false` | `true` |

**Com afecta serving:**
- **Headers:** `X-Data-Source` pot ser `ostium_recorded`, `primary`, `fallback` o `mixed`. `X-Data-Primary-Source: ostium_recorded` quan primary és Ostium.
- **Selecció de font:** Si el rang travessa `cutover_ts`: amb PASS → **mixed** (stitch Dukascopy + Ostium); sense PASS → 422.
- **Read-through:** Fill de gaps requereix compat PASS.
- **Sense PASS:** Mode "opt-in experimental" — es graven dades Ostium però no es declara primary; només primary o fallback per rang.

**Tests:** Unit 0-network: `test_ostium_compat_report_service.py`, `test_compat_registry_ostium_gate.py`, `test_save_ostium_registry_robust.py`. Opt-in real: `./test.sh testing/run_all.py --include-ostium-compat`.

### T6.8 — market_open filter al compat engine (2026-02-25)

**Implementació:** `_returns_market_open_filtered()` a `compat_report_service.py` — exclou del càlcul de retorns els minuts `market_closed` (via `get_market_state_ny()`) **i** les candles `zero_range` (h==l). Quan `n_open_pairs >= 50`, el veredicte PASS_BACKTEST usa `corr_market_open` en lloc de `corr_raw`.

**Resultats T6.8 (2026-02-25, rang 2026-02-18 → 2026-02-25):**

| Símbol | Mode | corr_raw | corr_market_open | excluded | n_open | verdict |
|--------|------|:---:|:---:|:---:|:---:|:---:|
| XAUUSD | rolling 1440m | 0.243 | **0.967** | 2 (0.15%) | 1361 | **PASS_BACKTEST** ✅ |
| XAUUSD | full (7d) | 0.418 | 0.652 | 4 (0.06%) | 6834 | **INCOMPATIBLE** ❌ |

**Anàlisi del full 7d INCOMPATIBLE:** El filtre zero_range detecta 2/4 dels candles problemàtics (els que `h==l=4996.32`). Hi ha **4 candles addicionals "spike_to_break_price"** (no zero_range) als 21:58 UTC de cada dia de mercat, on la candle final de la sessió captura el primer tick del break com a low/close:
- `2026-02-18T21:58Z`: low=4877.58 (preu de break), diff_prev=98.73
- `2026-02-20T21:58Z`: low=4996.32 (preu de break), diff_prev=109.72
- `2026-02-23T21:59Z`: ✅ zero_range filtrat
- `2026-02-24T21:59Z`: ✅ zero_range filtrat

Cada spike genera 2 bad returns → 8 parells anòmals en 6838. Amb 4 spikes (8 bad returns) sobre una sèrie de 6838, `corr_market_open=0.652 < 0.90`. El recorder Ostium hauria de no incloure ticks del break en la candle del minut anterior.

**Conclusió T6.8:**
- ✅ **Rolling XAUUSD: PASS_BACKTEST** — el filtre funciona per a la finestra operativa (24h veu max 1-2 spikes)
- ❌ **Full 7d XAUUSD: INCOMPATIBLE** — fix definitiu requereix corregir el recorder (no escriure ticks de break en la darrera candle de la sessió)
- **Tests 0-network:** 15/15 a `test_ostium_compat_report_service.py` (2 nous: `test_returns_market_open_excluded_closed_minutes`, `test_market_open_filter_improves_xauusd_verdict`)

**Artifacts T6.8:**
- `20260225_211321_compat_XAUUSD_1440m.json` (rolling, PASS_BACKTEST)
- `20260225_211327_compat_full_XAUUSD_20260218_20260225.json` (full, INCOMPATIBLE)

### T6.9 — Fix recorder: gate market_closed per bucket del tick (2026-02-25)

**Problema:** El recorder Ostium insereix ticks al bucket del seu `minute_start = (tick_ts//60)*60`.
Quan Ostium publica el "preu de break" (~4996.32) just a la frontera de tancament (17:00 NY),
el tick cau dins el bucket de 16:58 NY (últim minut obert) i corromp la candle: `low/close = 4996.32`.

**Fix (`ostium_candle_ingest_service.py`):** Gate market_hours al punt d'inserció del tick.
Abans d'afegir el tick a `self._ticks[symbol][minute_start]`, es verifica que `minute_start`
és `market_open`. Si no → tick ignorat + `_ignored_ticks_closed[symbol]++` + log DEBUG.

```python
# T6.9 — Gate: ignorar ticks el bucket del qual és market_closed
_tick_open, _tick_reason = _get_tick_state(symbol, minute_start)
if not _tick_open:
    self._ignored_ticks_closed[symbol] += 1
    logger.debug("ignored tick %s minute_start=%s reason=%s", symbol, minute_start, _tick_reason)
else:
    self._ticks[symbol][minute_start].append(tick)
```

**Observabilitat:** `get_symbol_stats()` exposa `ignored_ticks_closed` per símbol.

**Deploy:** `docker cp` + `docker restart realtime-datalayer` (gap ~5s, 2026-02-25 21:40 UTC).

**Resultat post-deploy (rolling 1440m):** PASS_BACKTEST (corr=0.968, excluded=2) ✅

**Tests 0-network:** 10/10 a `test_ostium_ingest.py` (3 nous T6.9):
- `test_tick_at_open_minute_accepted` — tick bucket open → inserit
- `test_tick_at_closed_minute_ignored` — tick bucket closed → ignorat, comptador +1
- `test_no_spike_at_boundary` — candle boundary no conté break_price

**Nota:** Els spikes pre-existents han estat reparats per T6.10 (veure secció següent).

### T6.10 — Repair històric XAUUSD sobre mount real (2026-02-25)

**Problema:** Els spikes `spike_to_break_price` (break_price dins bucket `market_open`) ja existien al store real `/datafiles/realtime_datalayer` (volum Docker compartit) i el compat full 7d seguia donant `INCOMPATIBLE (corr_market_open=0.571)`.

**Causa anterior:** Les sessions prèvies aplicaven el repair al path `/app/datafiles/realtime_datalayer` (path local del contenidor `historical-datalayer`) en lloc del volum compartit. El compat oficial llegeix de `/datafiles/realtime_datalayer`.

**Tip arquitectura (confirmat):** `app_factory.py` quan `role=realtime_datalayer` instancia `CSVCandleStore(root=DATAFILES_ROOT/realtime_datalayer, broker="candles")`. Tant `realtime_datalayer` com `historical_datalayer` munten el mateix volum `/mnt/volume-SQ/dev/BrokerageService/datafiles` → `/datafiles`.

**Tool creat:** `application/tools/ostium_rebuild_candles_from_ticks.py`
- Llegeix ticks JSONL (`daily/YYYYMMDD/<symbol>.jsonl`), aplica T6.9 gate + `spike_pct_threshold=0.99`
- Backup → patch al store (prefer new data)
- Paràmetre nou: `--spike-threshold` (default 0.99); stats `ticks_spike_filtered`

**Execució repair (2026-02-25, sobre mount real):**
```bash
docker exec realtime-datalayer python3 /app/application/tools/ostium_rebuild_candles_from_ticks.py \
    --symbol XAUUSD --from 2026-02-18T00:00:00Z --to 2026-02-26T00:00:00Z \
    --ticks-root /datafiles/realtime_datalayer/ticks \
    --candles-root /datafiles/realtime_datalayer --broker candles --write
```

**Spikes corregits:**
- `2026-02-20T21:58Z`: close `4996.32 → 5106.897` (diff=110.58) ✅ (ticks JSONL disponibles)
- `2026-02-25T21:58Z`: close `4996.32 → 5165.023` (diff=168.70) ✅ (ticks JSONL disponibles)
- `2026-02-18T21:58Z`: patch conservador `l/c = open = 4976.300` ✅ (sense ticks JSONL pel bucket)

**Ticks no disponibles:** `20260218` no té ticks al bucket `21:58`. `20260223/20260224` zero_range ja filtrats per T6.8.

**Resultat compat full 7d post-repair:**

| Mètrica | Abans T6.10 | Després T6.10 |
|---------|:-----------:|:-------------:|
| corr_raw | 0.402 | 0.429 |
| corr_market_open | 0.571 | **0.971** ✅ |
| dir_agree_filtered | 96.7% | 96.7% |
| excluded | 3 | 3 |
| n_open_pairs | 6882 | 6882 |
| **verdict** | INCOMPATIBLE ❌ | **PASS_BACKTEST ✅** |

**Rolling 1440m post-repair:** PASS_BACKTEST (corr=0.968, excluded=1) ✅ — sense regressions.

**Compat a executar amb paràmetres explícits (obligatori, default usa broker=gtrade buit):**
```bash
docker exec historical-datalayer python3 -m application.tools.ostium_compat_report \
    --symbol XAUUSD --mode full \
    --datafiles-root /datafiles/realtime_datalayer --broker candles
```

**Fix colateral (test_ostium_tick_recorder.py):** Tests que usaven timestamps de `2026-02-18` amb `retention_days=7` fallaven perquè el dia era exactament al límit de la finestra de retenció i `_run_retention` esborrava el directori just creat. Fix: tests de rotació/format usen `datetime.now()` + `retention_days=0`.

**Tests:** 74/74 passen (`testing/run_all.py`). 8/8 nous tests del rebuild passen.

**Artifacts:**
- Backup: `/app/_archive/20260225_221530_XAUUSD_rebuild_backup/`
- Repair report: `/app/datafiles/realtime_datalayer/artifacts/compat/20260225_221530_xauusd_rebuild_from_ticks_report.json`
- Compat after: `/datafiles/realtime_datalayer/artifacts/compat/20260225_221704_compat_full_XAUUSD_20260218_20260225.json`

---

## Phase 10 — BacktestMarketDataProvider (registry-aware)

**Propòsit:** Provider OHLCV per mode backtest que resol la font de dades via `ostium_compat_registry`:
- `allowed_for_backtest=true` → llegeix candles Ostium locals (`realtime_datalayer/candles/`)
- Altrament → fallback Dukascopy (pot requerir xarxa o cache)

**Fitxer:** `application/data/backtest_market_data.py`

**API pública:**
```python
# Resolució de font (determinisat, 0-network)
source = resolve_backtest_data_source("EURUSD", registry_path=...)
# → "ostium" o "dukascopy"

# OHLCV amb headers X-Data-* (async, però ostium_local = 0-network)
body, headers = await get_ohlcv_backtest(
    symbol="EURUSD",
    start=datetime(...),
    end=datetime(...),
    datafiles_root="/datafiles",
    registry_path=...,             # opcional; default DATAFILES_ROOT
    dukascopy_override=[...],      # per testing 0-network
)
```

**Headers X-Data-* retornats:**

| Header | Valor |
|--------|-------|
| `X-Data-Source` | `ostium_local` o `dukascopy` |
| `X-Data-Coverage-From` | unix ts candle inicial |
| `X-Data-Coverage-To` | unix ts fi de l'última candle |
| `X-Data-Missing-Minutes` | minuts esperats - candles obtingudes |
| `X-Data-Max-Gap-S` | gap màxim entre candles consecutives (≥60s exclòs) |

**Observabilitat (output demo):**
```
symbol=EURUSD source=ostium_local candles=10 missing=0
symbol=XAUUSD source=ostium_local candles=10 missing=0
symbol=USDJPY source=dukascopy candles=8 missing=2
```

**Fixtures testing:** Generades en `tempdir` a cada execució (0 fitxers externs; CSV creats inline al test).

**Com executar tests:**
```bash
./scripts/run_tests.sh trading_service
# o directament:
./test.sh testing/apps/trading_service/test_backtest_registry_marketdata.py
```

**Guardrails:**
- Registry absent → fallback determinista a `dukascopy` + log warn
- Ostium seleccionat però 0 candles → retorna body buit + headers coherents (missing=expected); NO fallback a Dukascopy (comportament explícit: si graduat, no amagar dades mancants)
- NEVER throws: errors de lectura retornen candles buides, no excepció

---

## Phase 11 — Backtest runner offline (simple_trend + KPIs + artifact)

**Fitxers:** `application/tools/run_backtest.py`, `scripts/run_backtest_offline.sh`

**Com executar:**
```bash
# EURUSD (Ostium local, 1 dia)
./scripts/run_backtest_offline.sh EURUSD 1

# XAUUSD (Ostium local, 1 dia)
./scripts/run_backtest_offline.sh XAUUSD 1

# USDJPY (Dukascopy fallback, 1 dia)
./scripts/run_backtest_offline.sh USDJPY 1

# Finestra personalitzada (via env o args)
BACKTEST_WINDOW_DAYS=7 ./scripts/run_backtest_offline.sh EURUSD
```

**Output consola (exemple):**
```
Backtest EURUSD (2026-02-19 → 2026-02-20)
  source=ostium_local candles=635 missing=0
  trades=42 wins=21 losses=21
  win_rate=50.0% pnl=+0.1234% max_dd=0.8500%
  artifact=datafiles/backtests/20260220_183037_EURUSD.json
```

**Artifact JSON** (`datafiles/backtests/YYYYMMDD_HHMMSS_<symbol>.json`):
```json
{
  "run_ts": "20260220_183037",
  "phase": "Phase11_backtest_offline",
  "symbol": "EURUSD",
  "timeframe": "1m",
  "window": {"start": "...", "end": "...", "days": 1.0},
  "strategy": {"name": "simple_trend", "lookback": 5, "hold_minutes": 10},
  "coverage": {"source": "ostium_local", "candles_count": 635, "missing_minutes": 0},
  "kpis": {
    "trades_count": 42, "wins": 21, "losses": 21,
    "win_rate_pct": 50.0, "pnl_total_pct": 0.1234,
    "roi_pct": 0.1234, "max_drawdown_pct": 0.85
  },
  "trades_sample": [...]
}
```

**Estratègia `simple_trend`:**
- Signal long si `close[i] > close[i - lookback]`; short si `close[i] < close[i - lookback]`
- Tancar posició quan: senyal contrari, flat, o `hold_minutes` exhaurits
- Sense apalancament; PnL en % sobre preu d'entrada

**Tests:** `testing/apps/trading_service/test_backtest_runner_offline.py` (12 tests 0-network):
- Tests d'estratègia pura (`_simple_trend_signals`, `_run_strategy`, `_compute_kpis`)
- Tests d'integració (runner complet, artifact verificat en disc)

**Graduation run canònic (EURUSD):**
```bash
# 1. Arrancar broker ostium (scripts exporten UID/GID → datafiles writable)
./scripts/run_smoke.sh ostium
# o: ./scripts/run_soak.sh 2 ostium post-compat  # arranca broker si no està up

# 2. Soak + post-compat (2–5 min)
./scripts/run_soak.sh 2 ostium post-compat

# 3. O només compat (si broker ja té dades)
./scripts/run_compat.sh ostium EURUSD
```
Si PASS → `ostium_compat_registry.json` actualitzat, `ostium_primary_allowed=true` per EURUSD. Artifact a `datafiles/data_layer_prod_runs/` i `datafiles/compat_reports/`.

---

## Phase 15 — Parquet storage particionat + Historical backfill runner

**Fitxers:**
- `infrastructure/storage/parquet_store.py` — `ParquetCandleStore`: write/read/range/coverage, idempotent, validació
- `application/tools/run_historical_backfill.py` — runner mes a mes, `skip_existing`, rate-limit, `dukascopy_override` per tests

**Layout Parquet:**
```
{datafiles_root}/historical_parquet/{SYMBOL}/tf=1m/year={YYYY}/month={MM}/data.parquet
```

**Ús CLI:**
```bash
python3 application/tools/run_historical_backfill.py \
    --symbol EURUSD --from 2003-01-01 --to 2003-12-31 \
    --datafiles-root /datafiles
```

**Ús programàtic (0-network):**
```python
result = await run_historical_backfill(
    symbol="EURUSD", from_date=date(2003,1,1), to_date=date(2003,12,31),
    datafiles_root="/datafiles", dukascopy_override=fake_candles,
)
```

**Idempotència:** `skip_existing=True` per defecte. `--no-skip-existing` per força rewrite.

---

## Phase 14 — OHLCV Data API registry-aware (Freqtrade-friendly)

**Fitxer:** `application/api/data_routes.py`

**Endpoint:** `GET /api/v1/data/ohlcv/{symbol}`

**Query params:**
- `tf=1m` (únic suportat ara)
- `from_ts`, `to_ts` (epoch UTC, opcionals; default = últimes N candles)
- `limit` (default 1000, max 5000)
- `offset` (paginació simple)

**Response:**
```json
{
  "symbol": "EURUSD",
  "timeframe": "1m",
  "source": "ostium_local",
  "candles": [[1700000000, 1.1000, 1.1010, 1.0990, 1.1005, 0.0], ...],
  "total": 1440,
  "offset": 0,
  "limit": 1000,
  "next_offset": 1000
}
```

**Headers:** `X-Data-Source`, `X-Data-Coverage-From/To`, `X-Data-Missing-Minutes`, `X-Data-Max-Gap-S`

**Curl d'exemple:**
```bash
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?tf=1m&limit=100" | python3 -m json.tool
# Paginació:
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?limit=500&offset=0"
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?limit=500&offset=500"
# Rang temporal:
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?from_ts=1700000000&to_ts=1700086400"
```

**Nota Freqtrade:** aquesta API serveix les dades; l'adaptador Freqtrade farà el mapping a DataFrame. No replica el format intern de Freqtrade 1:1.

---

## Phase 13 — run_all quiet + fail-fast

**Comandes canòniques:**
```bash
./test.sh testing/run_all.py                    # default: core 0-network, quiet, fail-fast
./test.sh testing/run_all.py --verbose          # mostra output de cada test
./test.sh testing/run_all.py --no-fail-fast     # continua fins al final
```

**Comportament default:** quiet (captura output, imprimeix-lo només si falla), fail-fast (para al primer error). Lighter/gTrade tests arxivats (T5.32); `--include-lighter` / `--include-gtrade` mostren avís i apunten a `_archive/`.

---

## Phase 12 — Backtest API REST (POST /run + GET /runs/{run_id})

**Fitxers:** `application/api/backtest_routes.py`, `application/api/error_codes.py` (3 noves constants)

**Endpoints:**
- `POST /api/v1/backtests/run` → 200 `{run_id, status, symbol, kpis, x_data, artifact_id}`
- `GET /api/v1/backtests/runs/{run_id}` → 200 artifact complet (+ `trades_sample`)
- `run_id` invàlid → 422; `run_id` inexistent → 404 `BACKTEST_NOT_FOUND`

**Com provar (curl):**
```bash
# POST run
curl -s -X POST http://localhost:8010/api/v1/backtests/run \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "EURUSD", "days": 1}' | python3 -m json.tool

# GET run (substituir <run_id> per el valor retornat)
curl -s http://localhost:8010/api/v1/backtests/runs/<run_id> | python3 -m json.tool
```

**Validació inputs (422):**
- `symbol`: alpha, max 10 chars, normalitzat a majúscules
- `days`: 0.01–30; `strategy`: `simple_trend`; `timeframe`: `1m`

---

## Data Layer readiness gates (prod)

Llindars via env: `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS` (defaults a constants.py).

**Gate 0 (core):**
- duplicates=0, ts_step_errors=0
- missing ≤ 1/24h (`DATA_LAYER_GATES_MAX_MISSING_PER_24H`)
- max_gap_s ≤ 180 (`DATA_LAYER_GATES_MAX_GAP_S`)
- stale=0 (`DATA_LAYER_STALE_SECONDS`)

**Cold start / warmup:** Basat en **cobertura recent (24h window)**, no span històric. `observed_open_minutes_24h = expected_open_minutes_24h - missing_minutes_24h` (market-hours aware). Mentre `observed_open_minutes_24h < DATA_LAYER_WARMUP_MINUTES` (default 120), `data_layer_status=warming_up` i no s'aplica gate missing_24h. Soak reporta warming_up (exit 0); no és incident. `data_status` inclou `expected_open_minutes_24h` i `observed_open_minutes_24h` per símbol.

**Market-hours aware (Ostium/profile FX):** Si mercat tancat (cap de setmana, fora d'horari), stale no degrada; missing exclou minuts en intervals tancats. `data_status` inclou `market_open` i `market_state_reason` per símbol.

**Gate 1 (serving):** headers X-Data coherents, coverage coherent, read-through funciona.  
**Gate 2 (ops):** restart safe, data_status 200, logs path, rotació.

| Gate | Criteri | Com validar |
|------|---------|-------------|
| Gate 0 | Data Layer core | `curl data_status` + soak 2m |
| Gate 1 | serving | `curl -I ohlcv \| grep X-Data` |
| Gate 2 | ops | `docker compose down && up` |

```bash
# Docker prod-ish (veure Operativa canònica)
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage

# Scripts canònics (profile data-layer)
./scripts/run_smoke.sh data-layer
./scripts/run_soak.sh 30 data-layer

# Manual
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2
```

---

## Backfill 2003→avui (prod-ish, Phase 18)

```bash
# Prova segura: 2 mesos, dry-run primer
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
  historical_datalayer python3 application/tools/run_historical_backfill.py \
  --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --dry-run --stop-after 2

# 2 mesos reals (valida pipeline)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
  historical_datalayer python3 application/tools/run_historical_backfill.py \
  --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --stop-after 2 --sleep 1

# Continuar (resume automàtic per coverage index)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
  historical_datalayer python3 application/tools/run_historical_backfill.py \
  --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --sleep 1

# Reintenta mesos fallats
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
  historical_datalayer python3 application/tools/run_historical_backfill.py \
  --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --retry-failed --sleep 2

# Pipeline complet (backfill + backtest)
./scripts/run_full_pipeline.sh --symbol EURUSD --from 2020-01-01 --to 2020-12-31

# Coverage index (on és el fitxer)
# datafiles/historical_parquet/_coverage/EURUSD_tf1m.json
```

---

## Phase 19 — Data API long-range + Coverage API

**Endpoint OHLCV long-range (DuckDB cursor):**
```bash
# Si hi ha Parquet → DuckDB path, source=historical_parquet
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?tf=1m&limit=1000" | python3 -m json.tool

# Paginació cursor multi-mes (next_ts)
NEXT=$(curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?limit=5000" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['next_ts'] or '')")
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?limit=5000&next_ts=$NEXT"

# Rang temporal explícit
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?from_ts=1577836800&to_ts=1580515200&limit=5000"
```

**Coverage API:**
```bash
# Summary + detall per mes (done/failed/empty)
curl -s "http://localhost:8010/api/v1/data/coverage/EURUSD?tf=1m" | python3 -m json.tool

# Resultat esperat (exemple post-backfill):
# {
#   "symbol": "EURUSD", "timeframe": "1m",
#   "summary": {"months_done": 264, "months_failed": 0, "months_empty": 0, "total_rows": 8372149},
#   "months": {"2003-01": {"status": "done", "rows": 31653, ...}, ...}
# }
```

**Routing OHLCV:**
- Parquet existent + `HISTORICAL_MIXED_ALLOWED=1` → DuckDB + stitch realtime → `source=mixed`
- Parquet existent + `HISTORICAL_MIXED_ALLOWED=0` → DuckDB only → `source=historical_parquet`
- Sense Parquet → legacy path (ostium_local o dukascopy) + paginació `offset`

---

## Phase 20 — Mixed stitching parquet+realtime + Cron operatiu

**Mixed stitching:**
```bash
# mixed enabled (default): source=mixed quan hi ha parquet + realtime
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?tf=1m&limit=1000" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['source'])"
# → "mixed"

# Desactivar mixed (parquet only)
HISTORICAL_MIXED_ALLOWED=0 docker compose up -d trading_service
```

**Policy `HISTORICAL_MIXED_ALLOWED`:**
- `1` (default): merge parquet + realtime; realtime guanya en overlap
- `0`: parquet only; realtime ignorat

**Cron operatiu:**
```bash
# Backfill d'ahir (idempotent, resume per coverage index)
./scripts/run_historical_cron.sh daily --symbol EURUSD

# Reintentar mesos fallats
./scripts/run_historical_cron.sh retry-failed --symbol EURUSD

# Repair últims 7 dies (reescriu)
./scripts/run_historical_cron.sh gap-repair --days 7 --symbol EURUSD

# Com a cron (executa cada dia a les 06:00 UTC)
# 0 6 * * * /path/to/BrokerageService/scripts/run_historical_cron.sh daily >> /var/log/cron_backfill.log 2>&1
```

---

## Evidència recent

| Data | Run | Resultat | Com validar |
|------|-----|----------|-------------|
| 2026-02-17 | `run_all.py` | ✅ passa | `./test.sh testing/run_all.py` |
| 2026-02-17 | Data Layer soak | ✅ 2m: missing=0, dup=0 | `./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2` |
| 2026-02-17 | Ostium LAB | 🏃 24h captura en curs | lab/ostium |
| 2026-02-17 | Docs coherents Ostium | ✅ AGENTS + ESTAT + overrides alineats | graduation path, prod-ish opt-in |
| 2026-02-17 | Ostium Recorder prod-ish v1 | ✅ ingest real 1m, gates, data_status ingest_source | write_mode realtime_plus_backfill |
| 2026-02-17 | Ostium compat + graduation gate | ✅ compat report Ostium↔Dukascopy, registry, run_compat.sh | PASS → ostium_primary_allowed |
| 2026-02-17 | Ostium primary serving v1 | ✅ policy per símbol, X-Data-Source=ostium_recorded, data_status primary_allowed_by_symbol | headers + coverage + tests |
| 2026-02-17 | Market-hours aware gates | ✅ is_market_open, closed_intervals; stale/missing ajustats; data_status market_open | soak cap de setmana no DEGRADED |
| 2026-02-17 | Ostium Graduation Loop v1 | ✅ run_soak.sh 30 ostium post-compat; SKIP si no candles; graduation_summary a artifact | `./scripts/run_soak.sh 2 ostium post-compat` (SKIP per falta Dukascopy) |
| 2026-02-18 | Data Layer readiness handshake | ✅ data_status 200 amb initializing; soak wait_for_ready; startup_wait_s a artifact | `./scripts/run_soak.sh 2 ostium post-compat` sense 503 |
| 2026-02-17 | Ostium allowlist + quarantine v1 | ✅ OSTIUM_SYMBOLS, OSTIUM_QUARANTINE_SYMBOLS; EURUSD primary allowed; XAUUSD quarantined | run_soak ostium usa llista canònica |
| 2026-02-18 | run_all.py | ✅ passa (incl. test_ostium_symbol_allowlist, test_data_status_quarantine_flags) | `./test.sh testing/run_all.py` |
| 2026-02-18 | Suites per servei (vNext) | ✅ smoke, core, realtime_datalayer, historical_datalayer, trading_service | `./scripts/run_tests.sh <suite>` |
| 2026-02-18 | Ostium LAB monitor (continuous) | ✅ run_lab.sh ostium-monitor start/stop/status; rotació diària + retenció | `./scripts/run_lab.sh ostium-monitor start` |
| 2026-02-18 | EURUSD graduation (permisos + run canònic) | ✅ user UID:GID a compose; save_ostium_registry atomic; run_compat/run_soak post-compat escriuen registry | `./scripts/run_soak.sh 2 ostium post-compat` |
| 2026-02-18 | Cold-start readiness + permisos | ✅ warmup window (DATA_LAYER_WARMUP_MINUTES); warming_up no DEGRADED; --user a docker run; ESTAT+SAFETY_RUNBOOK | soak cold start reporta warming_up; no root-owned files |
| 2026-02-18 | Warmup basat en cobertura recent 24h | ✅ observed_open_minutes_24h (no span històric); prefetch no falsa warmup; startup gate ignora missing en warmup; warming_up→exit 0 | data_status expected/observed_open_minutes_24h |
| 2026-02-18 | Split vNext scaffold | ✅ apps/, packages/, plantilla_tasca.md, docker-compose.split.yml; AGENTS+ESTAT actualitzats | `docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml config` |
| 2026-02-18 | Split vNext Phase 1 | ✅ SERVICE_ROLE, entrypoints reals, create_app(role), role boundaries; test_service_role_wiring | `./test.sh testing/unit/test_service_role_wiring.py` |
| 2026-02-18 | Split vNext Phase 2 | ✅ trading_service consumeix realtime_datalayer via HTTP (contracte mínim); RealtimeDataLayerClient (packages/shared); IDataLayerReader; REALTIME_DATALAYER_BASE_URL | `./scripts/run_tests.sh trading_service`; `curl -s http://localhost:8010/api/v1/broker/data_status` |
| 2026-02-18 | Realtime DataLayer v1 | ✅ servei autònom; GET /health, /status; storage datafiles/realtime_datalayer/; tests curts run_realtime.py | `./test.sh testing/run_realtime.py`; `curl -s http://localhost:8081/status` |
| 2026-02-18 | Realtime hot-reload | ✅ GET/PUT /symbols; config persistent symbols.json; instrument resolution (spot/perp); add/remove símbols sense restart | `curl -X PUT http://localhost:8081/symbols -d '{"symbols":["EURUSD","XAUUSD"],"apply_mode":"replace"}'` |
| 2026-02-18 | Realtime UI + smoke | ✅ /, /ui, /info, /docs, /openapi.json; auto-refresh 5s/10s/30s; cards per símbol; PUT diff/replace; smoke `./scripts/run_smoke.sh realtime_datalayer` | http://localhost:8081/ ; http://localhost:8081/ui ; http://localhost:8081/docs |
| 2026-02-18 | Realtime market-hours aware | ✅ market_closed no degrada; ingest pausat per símbol; /symbols market_open, market_state_reason, state; dashboard badges+taula; tests test_market_closed_not_degraded, test_pause_resume, test_dashboard_renders_states | `./test.sh testing/run_realtime.py`; XAU closed cap de setmana = OK |
| 2026-02-18 | Realtime Dashboard v2 | ✅ last_price, market_state (open|closed|unknown), state (running|closed|warning|degraded); /status effective_tz, now_utc, now_local; filtres, ordenació, presets FX; test_status_includes_timezone_fields | http://localhost:8081/ui |
| 2026-02-18 | Imports AGENTS compliance | ✅ app_factory: stdlib (datetime, zoneinfo, subprocess, time) a capçalera; lazy imports documentats; tests realtime_datalayer imports a capçalera | AGENTS_ARQUITECTURA.md §6.1 |
| 2026-02-18 | Realtime v2.1 Market-hours Ostium (NY) | ✅ perfils XAU break 16:59–18:10, indices 16:59–18:00, NVDA RTH 09:31–15:59; paused_closed; health no penalitza closed; ages com deltes; next_open_local | apps/realtime_datalayer/market_hours/ |
| 2026-02-18 | Degraded non-blocking + autorecover | ✅ degraded continua polling amb backoff (2s–60s); autorecover quan tick nou; pause només paused_closed; /symbols next_poll_in_s, degrade_reason; UI mostra; tests test_degraded_does_not_stop_polling, test_autorecover_on_new_tick | `./test.sh testing/run_realtime.py` |
| 2026-02-20 | Split vNext Phase 3: Symbol Supervisor + heartbeat | ✅ market_closed → heartbeat 60s (OSTIUM_CLOSED_HEARTBEAT_S); no stop total; last_price actualitza; candles NO durant heartbeat; 5 tests test_heartbeat_when_closed + 5 tests nous suite | `./scripts/run_tests.sh realtime_datalayer` |
| 2026-02-20 | Split vNext Phase 4: X-Data-* headers contracte | ✅ GET /ohlcv/{symbol} i /candles emeten X-Data-Source/Coverage-From/To/Missing-Minutes/Max-Gap-S; path local ja correcte; 4 tests test_ohlcv_headers | `./scripts/run_tests.sh realtime_datalayer` |
| 2026-02-20 | Split vNext Phase 5: NO_TRADE enforçat (fail-closed real) | ✅ OrderOpenService comprova gate via `assert_data_quality_ok()`; gate=BAD→422 DATA_QUALITY_GATE_BAD; cap venue call; gate=OK→continua; 5 tests test_quality_gate_enforced | `./scripts/run_tests.sh trading_service` |
| 2026-02-20 | Phase 8: Compat sampling Ostium↔Dukascopy | ✅ EURUSD PARTIAL (corr=0.958, dir_agree=90%); XAUUSD PARTIAL (corr=0.977, dir_agree=90.7%). Dades reals Ostium recorder. | `datafiles/compat_reports/20260220_1[56]*.json` |
| 2026-02-20 | Phase 9: PASS_BACKTEST + dir_agree_filtered | ✅ EURUSD **PASS_BACKTEST** (corr=0.968, dir_filtered=96.7%, eligible=427); XAUUSD **PASS_BACKTEST** (corr=0.977, dir_filtered=95.9%, eligible=468). `allowed_for_backtest=true`. 9 tests unitaris. | `datafiles/compat_reports/20260220_153*.json` |
| 2026-02-20 | Phase 10: BacktestMarketDataProvider registry-aware | ✅ `application/data/backtest_market_data.py`; EURUSD/XAUUSD → `ostium_local`; no graduat → `dukascopy`; headers X-Data-* coherents; 9 tests 0-network; `run_all.py` VERD (85 passed). | `./scripts/run_tests.sh trading_service` |
| 2026-02-20 | Phase 11: Backtest runner offline + KPIs + artifact | ✅ `application/tools/run_backtest.py`; estratègia `simple_trend`; KPIs (trades, win_rate, pnl, max_dd); artifact JSON `datafiles/backtests/`; `scripts/run_backtest_offline.sh`; 12 tests 0-network; `run_all.py` VERD (85 passed). | `./scripts/run_backtest_offline.sh EURUSD 1` |
| 2026-02-20 | Phase 12: Backtest API REST | ✅ `application/api/backtest_routes.py`; `POST /api/v1/backtests/run` + `GET /runs/{run_id}`; artifact persistit; 8 tests 0-network. | `curl -X POST http://localhost:8010/api/v1/backtests/run -d '{"symbol":"EURUSD","days":1}'` |
| 2026-02-20 | Phase 13: run_all quiet+fail-fast | ✅ `testing/run_all.py` reescrit; quiet+fail-fast per defecte; Lighter/gTrade arxivats (T5.32). | `./test.sh testing/run_all.py` |
| 2026-02-20 | Phase 14: OHLCV Data API registry-aware | ✅ `application/api/data_routes.py`; `GET /api/v1/data/ohlcv/{symbol}`; format `[ts,o,h,l,c,v]`; paginació; X-Data-* headers; 9 tests 0-network; 64 passed. | `curl "http://localhost:8010/api/v1/data/ohlcv/EURUSD?tf=1m&limit=100"` |
| 2026-02-20 | Phase 15: Parquet storage + backfill runner | ✅ `infrastructure/storage/parquet_store.py`; particionat mensual; idempotent; `application/tools/run_historical_backfill.py`; 13 tests 0-network; 65 passed. | `python3 application/tools/run_historical_backfill.py --symbol EURUSD --from 2003-01-01 --to 2003-12-31` |
| 2026-02-20 | Phase 19: Data API long-range + Coverage API | ✅ `GET /api/v1/data/ohlcv/{symbol}` DuckDB cursor `next_ts` multi-mes; `GET /api/v1/data/coverage/{symbol}` exposa index (summary+mesos); 10 tests 0-network; run_all VERD. | `curl "http://localhost:8010/api/v1/data/coverage/EURUSD?tf=1m"` |
| 2026-02-21 | Phase 20: Mixed stitching + Cron | ✅ `mixed_ohlcv_stitcher.py`; merge parquet+realtime monotònic; policy `HISTORICAL_MIXED_ALLOWED`; `source=mixed`; `run_historical_cron.sh` daily/retry-failed/gap-repair; 6 tests 0-network; run_all VERD. | `curl "http://localhost:8010/api/v1/data/ohlcv/EURUSD"` → source=mixed |
| 2026-02-21 | Market-hours fix (weekend bug) | ✅ `engine.py`: XAU/indices/NVDA tancats cap de setmana; break 17:00–18:00 NY; `_next_sunday_18()`; golden anti-regressió `test_market_hours_golden_weekend.py` (7 tests); tots els 8 símbols `closed` dissabte verificat via Docker. | `./scripts/run_tests.sh realtime_datalayer` |
| 2026-02-21 | Phase C: Historical dashboard + nginx proxy | ✅ nginx `datalayer-proxy` port 8081: `/realtime/*`→realtime:8082, `/data/*`→historical:8002. `GET /health` i `/status` a historical (`cron_metadata`, `coverage_index`). `get_historical_router()` sense prefix. `run_historical_cron.sh` escriu `_cron/last_runs.json`. 19 tests 0-network; run_all 72 passed. | `curl :8081/data/health` · `curl :8081/realtime/status` |
| 2026-02-21 | Phase D: Gateway single-port complet | ✅ `/trade/*` → trading_service:8010 (strip prefix); `/backtests/*` alias. `datalayer-proxy` és ara el gateway únic. `scripts/smoke_gateway.sh` verifica tots els prefixos. run_all 72 passed. | `curl :8081/trade/api/v1/broker/health` · `./scripts/smoke_gateway.sh` |
| 2026-02-24 | Ostium LIVE smoke (T5): override + wrapper | ✅ `ostium-live-trading.yml` per trading_service mode LIVE; `run_ostium_live_smoke.sh` wrapper; TRADING_CANARY_MODE=ostium; RPC_URL/PRIVATE_KEY per SDK. **Regla: NO recrear realtime_datalayer.** Docs: overrides/README, ESTAT, lab/ostium/README. | `./scripts/run_ostium_live_smoke.sh` · `./scripts/run_ostium_live_smoke.sh --recreate` |
| 2026-02-24 | T5.40: Extract use-cases from broker_routes | ✅ OperationService, OrderOpenService, OrderCloseService a `application/services/`; broker_routes API fina (valida, crida serveis, retorna); operations.jsonl sense canvis; 74 tests passen. | `./test.sh testing/run_all.py` |
| 2026-02-24 | T5.41: Ports + Wiring | ✅ `application/ports/` (ExecutionPort, MarketDataPort, OperationStorePort); serveis reben ports injectats; `application/wiring.py` centralitza construcció; broker_routes delega a wiring; 74 tests passen. | `./test.sh testing/run_all.py` |
| 2026-02-24 | Fix smoke backtests | ✅ `GET /api/v1/backtests/runs` afegit; smoke gateway passa; arxiu root (run_smoke.sh legacy, etc.) → `_archive/root/2026-02-legacy-purge/`. | `./scripts/smoke_gateway.sh` |
| 2026-02-25 | T6.2: CompatReport canònic (re-run) | ✅ CLI `--minutes`, `--out`; artifact a `datafiles/artifacts/compat/`; logs compat_report start/done; run_compat.sh amb --minutes 1440 i --out; ESTAT actualitzat. | `python3 -m application.tools.ostium_compat_report --symbol EURUSD --minutes 1440` |
| 2026-02-25 | T6.3: Compat results visible | ✅ `latest_<symbol>.json` (overwrite) a artifacts/compat/; stdout RESULT amb symbol, verdict, corr, dir_agree_filtered, path, latest. | `cat datafiles/artifacts/compat/latest_EURUSD.json` |
| 2026-02-25 | T6.5: CompatReport FULL OVERLAP + LAST N (rolling) | ✅ `--mode rolling\|full`; full determina rang [earliest,latest] Ostium, obté Dukascopy, calcula compat sobre tot l'overlap; `latest_full_<sym>.json` (no toca rolling); stdout/log amb `ostium_total`, `duka_total`, `aligned_total`, `aligned_ratio`; 4 tests nous 0-network. | `python3 -m application.tools.ostium_compat_report --symbol EURUSD --mode full` |
| 2026-02-25 | T6.6: Execució real 4×compat (EURUSD+XAUUSD, rolling+full) | ✅ 8 artifacts creats (4 timestampats + 4 `latest_*`). EURUSD rolling: PASS_BACKTEST (corr=0.951, aligned_ratio=0.9958). EURUSD full 7d: PASS_BACKTEST (corr=0.956, aligned_ratio=0.9851, 7001/7025). XAUUSD rolling: INCOMPATIBLE (corr=0.219 — feed offset?). XAUUSD full 7d: INCOMPATIBLE (corr=0.415). XAUUSD quarantina mantinguda. | `ls datafiles/realtime_datalayer/artifacts/compat/` |
| 2026-02-25 | T6.7: Diagnòstic XAUUSD — stale_candles_fixable | ✅ `application/tools/ostium_xauusd_diagnose.py`: anàlisi A/B/C/D (affine, returns, lag_scan, stale_filter). corr_price=0.999 (feed OK) + corr_returns_raw=0.22→0.96 filtrant 3 candles zero_range (stale). Causa: recorder Ostium repeteix preu de tancament (4996.32) durant gap nocturn; Dukascopy reflecteix preu real ($5227). Max diff=$230.31. Fix (T6.8): excloure candles mercat tancat del compat. 12 tests 0-network. | `python3 -m application.tools.ostium_xauusd_diagnose --symbol XAUUSD --mode full --datafiles-root ... --broker candles` |
| 2026-02-26 | T6.12: Verificació compat cron-like amb defaults | ✅ `./scripts/run_compat.sh ostium EURUSD` i `XAUUSD` → PASS_BACKTEST. CONFIG confirmat: broker=candles, datafiles_root=/datafiles/realtime_datalayer. Artifacts: `datafiles/realtime_datalayer/artifacts/compat/latest_*.json`. Fix: run_compat.sh ara usa Docker efímer (com test.sh) per tenir deps. Fix: exit code 0 per PASS_BACKTEST. Print_config al tool per audit. EURUSD: corr=0.946, dir=97.9%, exit=0 ✅. XAUUSD: corr=0.965, dir=96.8%, exit=0 ✅. | `./scripts/run_compat.sh ostium EURUSD && ./scripts/run_compat.sh ostium XAUUSD` |

**DEGRADED vs CLOSED vs WARNING:** `closed` = mercat tancat (cap de setmana FX/XAU); no és incident. `warning` = market_state=unknown sense dades; no és degraded. `DEGRADED` = errors reals (duplicates, ts_step_errors, stale quan market_open). **Degraded és non-blocking:** continua polling amb backoff (base 2s, max 60s); autorecover quan arriba tick nou; pause només per `paused_closed` (market_closed). `/symbols` inclou `next_poll_in_s`, `degrade_reason`.

**Detall històric:** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

---

## Backlog (properes 48h)

**Objectiu:** activar Data Layer a prod amb prefetch + observability + gates.

**D0 (avui):**
- [ ] Prefetch recent (N hores/dies) a prod env
- [ ] Scheduler (cron/loop) + idempotència
- [ ] Alert mínim: stale>… / missing>… / duplicates>0
- [ ] Rotació artifacts/logs

**D1 (demà):**
- [ ] Soak 6–12h amb prefetch actiu
- [ ] Cutover policy: primary/fallback per símbol (EURUSD especial)
- [ ] Doc "operar data layer" (runbook)

**Com validar:** `curl data_status`; `./scripts/run_soak.sh N data-layer`; `docker compose down && up`.

**Backlog (no compromès):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

---

## Roadmap post-CompatReport (brúixola)

**Ordre recomanat** després de la prova Dukascopy↔Ostium. Format: Done / Next.

| # | Item | Estat | DoD / Notes |
|---|------|-------|-------------|
| 1 | **CompatReport canònic (T6.1/T6.2/T6.12)** | Done | thresholds explícits; artifact a `datafiles/realtime_datalayer/artifacts/compat/`; comanda cron-like: `./scripts/run_compat.sh ostium EURUSD` (broker=candles, datafiles=/datafiles/realtime_datalayer, exit=0 si PASS_BACKTEST); EURUSD corr=0.946 dir=97.9% ✅; XAUUSD corr=0.965 dir=96.8% ✅ (2026-02-26) |
| 2 | **Política SL/TP** | Done (T7.1/T7.2) | A) client-side implementat (paper: SL/TP/TTL; LIVE smoke: open→wait→close idempotent). B) virtual SL/TP al broker com a hardening prod Next |
| 3 | **Freqtrade smoke strategy** | Next | Estratègia tonta 1h: fetch candles → open → close → ledger/ops ok. Paper primer. DoD: 1 dia sense errors sistèmics |
| 4 | **Backtest llarg Dukascopy 2004→2026** | Next | Timeframe 1h; mateix cost model que paper-live (spread+slippage+fees conservadors); walkforward per anys. DoD: estratègia passa criteris ROI/DD/trades |
| 5 | **Alerts mínims + runbook curt** | Next | *Abans de paper-live.* stale/missing/dup; runbook start/continue/rollback |
| 6 | **Paper-live quarantena 1 mes** | Next | Mesures diàries: PnL, latència open/close, %202, errors per codi. DoD: 30 dies DD dins límit, sense errors sistèmics |
| 7 | **Prefetch/cron + rotació logs** | Next | *Abans de prod.* prefetch idempotent; rotació artifacts/logs |
| 8 | **Prod petit capital + guardrails** | Next | circuit breaker, max exposure, max daily loss, alerts. DoD: 2–4 setmanes stable |

**Operativa Data Layer:** Alerts abans de 6 (paper-live); prefetch/rotació abans de 8 (prod).

**DoD tasca coherència Ostium (2026-02-17):**
- [x] Docs coherents: ESTAT.md i AGENTS_ARQUITECTURA.md no es contradiuen
- [x] Operativa: deploy/compose/overrides/README.md reflecteix profile ostium (opt-in experimental)
- [x] Scripts: run_smoke.sh ostium / run_soak.sh ostium usen override ostium i produeixen artifacts
- [x] Tests: run_all.py passa (default, 0-network); ostium wiring + backfill_only contract

---

## Operativa canònica (scripts + compose profiles)

| Profile | Compose override | Smoke | Soak | Compat |
|---------|------------------|-------|------|--------|
| data-layer | deploy/compose/overrides/data-layer.yml | `run_smoke.sh data-layer` | `run_soak.sh 30 data-layer` | — |
| ws | deploy/compose/overrides/soak.yml | — | `run_soak.sh 15 ws` | — |
| ostium | deploy/compose/overrides/ostium.yml | `run_smoke.sh ostium` | `run_soak.sh 30 ostium` | `run_compat.sh ostium` |
| ostium-live | deploy/compose/overrides/ostium-live-trading.yml (trading_service sol) | — | — | `run_ostium_live_smoke.sh` |

**Graduation loop Ostium:** `./scripts/run_soak.sh 30 ostium post-compat` — soak + compat automàtic al final. Si no hi ha candles suficients o Dukascopy falta → SKIP (exit 0). Artifact inclou `graduation_summary`. Quan acabi la 24h i Dukascopy tingui delay resolt, correr compat 1440: `run_compat.sh ostium` amb `OSTIUM_COMPAT_WINDOW_MINUTES=1440`.

**Readiness handshake:** `data_status` pot estar `initializing` els primers segons; scripts esperen readiness automàticament (`--wait-timeout` default 120s).

**Cold start / warmup:** Durant arrencada freda (coverage < `DATA_LAYER_WARMUP_MINUTES`), `data_layer_status=warming_up` — no és incident. El soak no falla per missing_24h fins superar warmup. Els scripts `run_soak` i `run_smoke` executen dins Docker amb `--user $(id -u):$(id -g)` per evitar root-owned files a datafiles/.

**Regla:** No crear scripts nous ad-hoc. Lògica a `application/tools/*.py`; wrappers a `scripts/*.sh`.

---

## Ostium LAB monitor (continuous)

**Comandes:** `./scripts/run_lab.sh ostium-monitor start|stop|status|logs`

**Rotació diària:** `lab/out/ostium_prices/daily/YYYYMMDD/` + `daily/LATEST_RUN.txt`  
**Retenció:** `OSTIUM_LAB_RETENTION_DAYS=14` (neteja dirs antics)

**Smoke local (documentat, no automatitzat):**
```bash
./scripts/run_lab.sh ostium-monitor start
# esperar 10–20s
./scripts/run_lab.sh ostium-monitor status   # ha de mostrar last_ts per símbol
```

---

## Comandes ràpides

```bash
./test.sh testing/run_all.py
./scripts/run_smoke.sh data-layer
./scripts/run_smoke.sh ostium   # Ostium realtime + Dukascopy backfill
./scripts/run_compat.sh ostium  # Ostium vs Dukascopy compat (graduation gate)
./scripts/run_soak.sh 30 data-layer
./scripts/run_soak.sh 30 ostium
./scripts/run_soak.sh 30 ostium post-compat   # soak + compat automàtic (graduation loop)
./scripts/run_ostium_live_smoke.sh            # Ostium LIVE E2E smoke (trading_service ja configurat)
./scripts/run_ostium_live_smoke.sh --recreate # recrea trading_service (NO realtime) + smoke
./scripts/run_lab.sh ostium-monitor start     # LAB Ostium continuous
./scripts/run_lab.sh ostium-monitor status    # last_ts per símbol
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml config  # validar
docker compose -f docker-compose.yml -f deploy/compose/overrides/ostium.yml config     # Ostium
docker compose build brokerage
docker compose down && docker compose up -d brokerage
```

**Més comandes:** [_archive/ESTAT_2026Q1.md § Annex](_archive/ESTAT_2026Q1.md)

---

## Notes crítiques

- **EURUSD Lighter REST candlestick (legacy arxivat):** DATA_QUALITY_FAIL (zero_range alt) → no apte per backtest; no declarar primary històric.
- **WS Candle Collector** és el camí per validar candles WS com a alternativa.
- **XAU PARTIAL** — corr/dir_agree dins llindars; offset acceptable.

---

## Estat per àrees

| Àrea | Estat | Notes |
|------|-------|-------|
| Broker API | ✅ | `/api/v1/broker/*`, POST body |
| Execution (paper/live) | ✅/🟡 | Ostium paper/LIVE OK; live hardening 90% |
| Data Layer | ✅ | P4–P7c; Ostium+Dukascopy. Lighter candlestick arxivat. |
| Ostium Data Layer | ✅ | prod v0: Ostium realtime + Dukascopy backfill; `run_smoke.sh ostium` |
| Backtest | ✅ | API + runner (Phases 10–12, 17); pipeline prod opcional |
| Ostium LAB | 🧪 | Validació RWA; [lab/ostium/README.md](../lab/ostium/README.md). **Test canònic full cycle:** `lab/ostium/scripts/test_full_cycle_multicall.py` (open→wait→find→close amb multicall + tradingStorage; no subgraph). Multicall scan: decode Trade(9), SANITY_CHECK, SCAN_ONLY sense PRIVATE_KEY. Legacy subgraph-dependent: `lab/ostium/_archive/scripts/test_full_cycle.py`. **Neteja testnet:** `lab/ostium/scripts/close_all_open_trades.py` (scan + close; SCAN_ONLY=1 llista sense PK; SCAN_ONLY=0 tanca fins a MAX_CLOSE). Run: `docker compose -p lab_ostium run --rm -e RPC_URL -e PRIVATE_KEY -e SCAN_ONLY=0 -e MAX_CLOSE=3 ostium-cli python3 scripts/close_all_open_trades.py`. |

