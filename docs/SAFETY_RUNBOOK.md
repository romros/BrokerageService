# Runbook operatiu curt — BrokerageService

**Objectiu:** Document que obres quan hi ha un incident. Procediments mínims per detectar i actuar.

**Docs:** [ESTAT.md](ESTAT.md) · [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)

---

## 0) Regla d’or — MAI aturar live

**realtime_datalayer és el nostre gold:** guarda les dades Ostium (candles, ticks) en temps real.

| Acció | Permès? |
|-------|---------|
| Aturar `realtime_datalayer` | ❌ **MAI** |
| Recrear / rebuild `realtime_datalayer` | ❌ **MAI** (excepte finestra de manteniment planificada) |
| Recrear `trading_service` | ✅ Sí (live_on/live_off fan només això) |
| Recrear `historical_datalayer` | ✅ Sí |

**Per què:** Si atures realtime_datalayer perds ingest; les dades noves no es guarden. Les dades ja persistides queden al volum, però el flux viu es talla.

**Scripts segurs:** `live_on.sh`, `live_off.sh` — fan `--force-recreate trading_service` **ONLY**. Mai toquen realtime_datalayer.

**Soak Ostium (TASCA 2c):** El soak `run_soak_ostium_validation.sh` només fa checks HTTP i rollover dry-run. **No atura ni reinicia cap servei.** Requereix stack split en marxa (gateway :8081).

---

## 1) Preflight (TZ, env, build)

**TZ:** `CANONICAL_TZ=America/New_York`, `TZ=America/New_York` (container).

```bash
docker compose run --rm brokerage date
docker compose run --rm brokerage python3 -c "import time,datetime; print(datetime.datetime.now()); print(time.tzname)"
```

**Build:** Si has canviat codi → `docker compose build brokerage`

---

## 2) Health checks

```bash
curl -s http://localhost:8000/api/v1/broker/health
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=10" | grep -i x-data
```

**data_status:** candles_written, gaps_detected, last_candle_ts per symbol.  
**Headers X-Data-*:** Source, Coverage-From/To, Missing-Minutes, Max-Gap-S, Repair.

---

## 3) Incidents típics

### Exec / posicions

| Símptoma | Acció |
|----------|-------|
| `positions_after > 0` post e2e/smoke | `e2e_trade --settle-timeout-s 120` (force_close_remaining) |
| "Account not found" | Comprovar `LIGHTER_BASE_URL`, `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX` |

### OHLCV buit / no candles

**Símptoma:** `GET /ohlcv` retorna buit o 503.

**Diagnòstic:** `GET /api/v1/broker/data_status`. Si 503 → pipeline no wired. Si 200 → mirar `symbols` (candles_written, gaps_detected, last_candle_ts).

### Data Layer incidents (prioritari)

**symbol_state=DEGRADED:** Mirar `degrade_reason` a `data_status`. Si duplicates>0 o ts_step_errors>0 → writer aturat; no contaminar primary. Si stale o missing → restart pipeline; check upstream.

| Incident | Diagnòstic | Acció |
|----------|------------|-------|
| **Stale feed** (stale_seconds > X) | data_status, last_candle_ts | Restart pipeline; check upstream; mark degraded |
| **Missing minutes** | X-Data-Missing-Minutes, coverage | Activar read-through (serve-only); executar repair; no mutar primary |
| **Duplicates / ts_step_errors** | data_status, integrity | Hard stop (no declarar primary); symbol_state=DEGRADED; investigar writer |
| **503 / pipeline down** | health, data_status | Restart; check logs |
| **data_layer_status=initializing** | data_status 200 amb data_layer_status | Normal durant arrencada; scripts esperen readiness. Si persisteix >2 min → pipeline no arranca; check logs |
| **data_layer_status=warming_up** | data_status 200, observed_open_minutes_24h < warmup | Cold start: no és incident. Cobertura recent dins 24h encara insuficient. Soak retorna exit 0 (no fail). |

**Si soak diu warming_up:** No és incident. El broker encara no té prou **minuts recents** dins la finestra 24h (`observed_open_minutes_24h`). Què mirar: `curl -s .../data_status` → `data_layer_status=warming_up`, `symbols.EURUSD.observed_open_minutes_24h`. Quant esperar: ~120 min per defecte. Per provar ràpid: `DATA_LAYER_WARMUP_MINUTES=5`.

### Ostium ingest (profile ostium)

| Incident | Diagnòstic | Acció |
|----------|------------|-------|
| **Stale feed** (stale_seconds > threshold) | data_status, last_candle_ts per symbol | Check Ostium API; restart brokerage; symbol_state=DEGRADED |
| **Gaps / missing minutes** | data_status missing_minutes_24h, max_gap_s | Dukascopy backfill; comprovar trading hours Ostium |
| **Duplicates / ts_step_errors** | data_status degrade_reason | Hard stop ingest per symbol; investigar writer; no declarar primary |
| **ingest_enabled=false** amb OSTIUM_ENABLED=1 | data_status write_mode | Si write_mode=backfill_only → ingest OFF per disseny; usar realtime_plus_backfill |
| **Ostium API 429 / timeout** | Logs OstiumCandleIngestService | Retry automàtic; si persistent → DEGRADED |

**Comandes Ostium:** `./scripts/run_smoke.sh ostium`, `./scripts/run_soak.sh 30 ostium`, `curl -s .../data_status` (ingest_source=ostium_realtime quan actiu).

**Root-owned files:** Si `datafiles/` o `compat_reports/` queden root-owned: `sudo chown -R $(id -u):$(id -g) datafiles logs`. Els scripts usen `--user` a docker compose run per evitar-ho.

**Market hours:** Si `market_open=false` (cap de setmana, fora d'horari FX), `stale_seconds` no aplica; no degradar per "no ticks" quan és normal. `data_status` mostra `market_open` i `market_state_reason` per símbol.

### Ostium primary serving

| Incident | Diagnòstic | Acció |
|----------|------------|-------|
| **Primary Ostium però gaps** | X-Data-Missing-Minutes > 0, coverage window_72h missing | Activar read-through (`ENABLE_READ_THROUGH=1`); Dukascopy omple gaps; comprovar que compat PASS per mixed |
| **Registry desalineat** | data_status primary_allowed_by_symbol=true però compat no s'ha executat recent | Executar `./scripts/run_compat.sh ostium <symbol>`; si verdict FAIL → registry es sobrescriu; revisar artifact JSON |

**Compat cron-like (T6.12 — 2026-02-26):** Comanda periòdica recomanada (1×dia o post-incident):
```bash
./scripts/run_compat.sh ostium EURUSD  # exit 0 si PASS_BACKTEST
./scripts/run_compat.sh ostium XAUUSD  # exit 0 si PASS_BACKTEST
```
Espera: `CONFIG broker=candles datafiles_root=/datafiles/realtime_datalayer`; `verdict=PASS_BACKTEST`; `corr_market_open ~0.94–0.97`; `dir_agree_filtered >95%`; `ostium_total >1000`. Artifacts a `datafiles/realtime_datalayer/artifacts/compat/latest_<SYM>.json`.

---

## 3b) SL/TP client-side (T7.1)

**Política (paper + live):** SL/TP són condicions de tancament client-side; CLOSE sempre és MARKET.
- `PAPER_SL_PCT` (default 2%): % de pèrdua màxima des d'entry
- `PAPER_TP_PCT` (default 4%): % de guany des d'entry (RR 1:2)
- `PAPER_TTL_S` (default 3600s): forçar close si no toca SL/TP en 1h
- `PAPER_POLL_S` (default 5s): freqüència de polling

**Smoke paper (requereix trading_service up):**
```bash
# Cicle ràpid (TTL=60s, poll=2s)
python3 -m application.tools.run_paper_trade \
  --symbol EURUSD --side long --collateral 100 --leverage 5 \
  --ttl-s 60 --poll-s 2 --base-url http://localhost:8081
```
Espera: `CONFIG ...` + `OPEN ok position_id=...` + `MONITOR elapsed=... price=...` + `CLOSE reason=TTL|TP|SL` + `RESULT ... ok=True`.

**Rollback:** Si el runner no pot tancar per xarxa, tancar manualment:
```bash
curl -X POST http://localhost:8081/trade/api/v1/broker/orders/close \
  -H 'Content-Type: application/json' \
  -d '{"venue":"paper","position_id":"<id>","percent":100}'
```

---

## 3c) LIVE smoke mínim (T7.2)

**Tool:** `application/tools/run_live_smoke_trade.py` — cicle open→wait→close+idempotent.

```bash
# EURUSD, col·lateral mínim, wait 10s
python3 -m application.tools.run_live_smoke_trade \
  --venue ostium --symbol EURUSD --side long \
  --collateral 1.5 --leverage 2 --wait-s 10 \
  --base-url http://localhost:8081

# XAUUSD
python3 -m application.tools.run_live_smoke_trade \
  --venue ostium --symbol XAUUSD --side long \
  --collateral 1.5 --leverage 2 --wait-s 10 \
  --base-url http://localhost:8081
```

**Espera (stdout):**
```
CONFIG venue=ostium symbol=EURUSD ...
OPEN ok position_id=... open_ack_ms=...
WAIT wait_s=10.0s position_id=...
CLOSE ok close_ack_ms=...
CLOSE idempotent ok already_closed=true idem_ack_ms=...
RESULT symbol=EURUSD ... ok=True
ARTIFACT datafiles/realtime_datalayer/artifacts/trading/latest_live_smoke_EURUSD.json
```

**Artifact:** `datafiles/realtime_datalayer/artifacts/trading/latest_live_smoke_<SYMBOL>.json`

**Rollback:** Si el tool queda amb posició oberta (timeout/xarxa):
```bash
curl -X POST http://localhost:8081/trade/api/v1/broker/orders/close \
  -H 'Content-Type: application/json' \
  -d '{"venue":"ostium","position_id":"<id>","percent":100}'
```

**Flags (T7.2.1):**
- `--max-duration-s` (default 60): timeout global — si s'excedeix, fa best-effort close i exit=3
- `--close-retries` (default 3): intents de close abans de declarar error
- `--artifact-dir`: path on escriure el JSON (relatiu al CWD o absolut)
- `CONFIG` mostra `enable_live_trading` i `resolved_mode=LIVE|PAPER` per audit

---

## 3d) LIVE TTL-only monitor (T7.3)

**Tool:** `application/tools/run_live_ttl_trade.py` — open→poll preu→close per TTL.

```bash
# EURUSD TTL=60s, poll 5s, max 120s
python3 -m application.tools.run_live_ttl_trade \
  --venue ostium --symbol EURUSD --side long \
  --collateral 1.5 --leverage 2 \
  --ttl-s 60 --poll-s 5 --max-duration-s 120 \
  --base-url http://localhost:8081

# XAUUSD TTL=60s
python3 -m application.tools.run_live_ttl_trade \
  --venue ostium --symbol XAUUSD --side long \
  --collateral 1.5 --leverage 2 \
  --ttl-s 60 --poll-s 5 --max-duration-s 120 \
  --base-url http://localhost:8081
```

**Espera (stdout):**
```
CONFIG venue=ostium symbol=EURUSD ... enable_live_trading=1 resolved_mode=LIVE ...
OPEN ok position_id=... executed_price=... open_ack_ms=...
MONITOR poll=1 price=... source=price/latest elapsed=5s remaining=55s
MONITOR poll=2 price=... ...
...
TTL reached elapsed=60.1s ttl_s=60 → CLOSE position_id=...
CLOSE ok close_ack_ms=... reason=ttl
CLOSE idempotent ok already_closed=true
RESULT symbol=EURUSD close_reason=ttl poll_count=12 total_ms=... ok=True
ARTIFACT datafiles/realtime_datalayer/artifacts/trading/latest_live_ttl_EURUSD.json
```

**Artifact:** `datafiles/realtime_datalayer/artifacts/trading/latest_live_ttl_<SYMBOL>.json`
- Inclou: `poll_count`, `ttl_elapsed_s`, mostres de `monitor.samples` (price, source, elapsed)

**Rollback:** Si el tool no pot tancar (timeout/xarxa):
```bash
curl -X POST http://localhost:8081/trade/api/v1/broker/orders/close \
  -H 'Content-Type: application/json' \
  -d '{"venue":"ostium","position_id":"<id>","percent":100}'
```

**Flags:**
- `--ttl-s` (default 60): temps de vida de la posició
- `--poll-s` (default 5): interval de polling de preu
- `--max-duration-s` (default 120): timeout global (ha de ser > ttl_s + overhead close)
- `--close-retries` (default 3): intents de close en cas d'error
- Tolerant a errors transitoris de preu (continua fins TTL)

---

## 3e) Activar/desactivar LIVE — scripts canònics (T7.3.1)

**Scripts idempotents que fan `--force-recreate trading_service` ONLY. MAI toquen `realtime_datalayer`.**

### LIVE ON (Ostium testnet)
```bash
./scripts/live_on.sh
# o amb gateway directe:
./scripts/live_on.sh --base-url http://127.0.0.1:8010
```
**Requereix:** `lab/ostium/.env` amb `RPC_URL` i `PRIVATE_KEY`.

**Espera (stdout):**
```
=== LIVE ON: activant trading_service mode LIVE Ostium ===
  realtime_datalayer: Running → OK (no tocar)
  Aplicant override LIVE + recreant trading_service...
  Preflight → mode=live live_enabled=True
✓ Mode confirmed: LIVE (mode=live live_enabled=True)
```

### LIVE OFF (tornar a PAPER — rollback segur)
```bash
./scripts/live_off.sh
```
**No requereix** credencials. Sempre executa amb `ENABLE_LIVE_TRADING=0`.

**Espera (stdout):**
```
=== LIVE OFF: tornant trading_service a mode PAPER ===
  Aplicant override PAPER + recreant trading_service...
  Preflight → mode=paper live_enabled=False
✓ Mode confirmed: PAPER (mode=paper live_enabled=False)
```

**Verificació manual post:**
```bash
curl -s 'http://localhost:8081/trade/api/v1/broker/preflight?venue=ostium&symbol=EURUSD' | python3 -m json.tool
# → mode, live_enabled, ready
```

**Notes:**
- Exit 0 = mode confirmat; exit 3 = mode no verificat (però acció aplicada)
- `live_off.sh` és sempre segur (zero tx possible en mode paper)
- Overrides: `ostium-live-trading.yml` (LIVE) / `live.off.yml` (PAPER)

---

## 3f) Dades històriques — sync Dukascopy (T8.1)

### Sync complet un símbol (ex: XAUUSD 2003→avui)

```bash
./scripts/sync_xauusd_full.sh        # llança en background si no corre / mostra progrés si corre
```

### Sync manual via API

```bash
# Bloc 1
curl -X POST http://localhost:8081/data/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","tf":"1m","from":"2003-01-01","to":"2012-12-31"}'

# Bloc 2
curl -X POST http://localhost:8081/data/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","tf":"1m","from":"2013-01-01","to":"2022-12-31"}'

# Bloc 3 (fins avui)
curl -X POST http://localhost:8081/data/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","tf":"1m"}'
```

**Notes:**
- Idempotent: cridar 2 cops → 2n retorna `status=up_to_date, months_written=0`
- Màxim 10 anys per crida (guardrail)
- Fallats: `status=partial` — re-cridar per reintentar

### Comprovar coverage

```bash
curl -s http://localhost:8081/data/coverage/XAUUSD | python3 -c \
  "import sys,json; d=json.load(sys.stdin); s=d['summary']; print(s)"
```

---

## 3g) LAB Runner — backtest estratègies (T8.0)

### Córrer un backtest

```bash
# SmokeStrategy (pipeline-first)
./scripts/run_lab_backtest.sh --strategy smoke --symbol EURUSD \
    --tf 1h --from 2020-01-02 --to 2020-01-31

# SQ 0.423850 (Bollinger+ATR, XAUUSD — requereix dades sync)
./scripts/run_lab_backtest.sh --strategy sq_0423850 --symbol XAUUSD \
    --tf 1h --from 2016-01-01 --to 2026-01-01
```

**Artifacts generats:** `lab/runner/artifacts/<strategy>/<symbol>/<tf>/<from>_<to>/`
- `summary.json` — KPIs (n_trades, net_pnl_pct, win_rate_pct, max_drawdown_pct)
- `trades.csv` — entrada/sortida/pnl per trade
- `equity.csv` — corba d'equity (base 100)

**Rollback / aturar:** el backtest és offline (no toca producció). Ctrl+C segur.

---

## 4) Kill switches

| Variable | Efecte |
|----------|--------|
| `ENABLE_LIVE_TRADING=0` | Paper (zero tx). Default. |
| `ENABLE_LIVE_TRADING=1` | Permet execució real LIVE. |
| `USE_FAKE_PRICE_FEED=1` | Preus fake (sense xarxa). |
| `USE_FAKE_PRICE_FEED=0` | Preus reals (cal .env Lighter). |
| `OSTIUM_ENABLED=1` + `DATA_LAYER_WRITE_MODE=realtime_plus_backfill` | Ostium ingest actiu (profile ostium). |
| `DATA_LAYER_WRITE_MODE=backfill_only` | Ostium ingest OFF (només backfill Dukascopy). |
| `ENABLE_READ_THROUGH=1` | Gap repair serve-only (no muta store). |

**On:** `.env` o `docker-compose.yml` environment.

**Guards:** `MAX_OPEN_POSITIONS`, `MAX_NOTIONAL_USDC` (veure `application/config/live_guards_config.py`).

**Reconcile:** ReconcileService compara posicions venue vs tracking. Diff → missing_locally, extra_locally. Logs: stdout; `datafiles/smoke_runs/` si smoke --repeat.

---

## 5) Recovery playbooks

| Situació | Acció |
|----------|-------|
| **Restart** | `docker compose down`; `docker compose up -d brokerage` (amb override si Data Layer: `-f deploy/compose/overrides/data-layer.yml`) |
| **Backfill / repair** | BackfillService (lifespan) + read-through (GET ohlcv si `ENABLE_READ_THROUGH=1`); test gap repair arxivat: `_archive/testing/2026-02-legacy-purge/integration/test_gap_repair_flow.py` |
| **Disable symbol** | Env: `SYMBOLS`, `LIGHTER_SYMBOLS`, `BACKFILL_SYMBOLS`; no policy registry per ara |
| **Degrade mode** | Fallback-only (no mixed); 422 mixed si compat FAIL |

---

## 6) Comandes essencials (10 línies)

```bash
./test.sh testing/run_all.py
./scripts/run_smoke.sh data-layer
./scripts/run_soak.sh 30 data-layer
curl -s http://localhost:8000/api/v1/broker/data_status
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml config  # validar
docker compose build brokerage
docker compose down && docker compose up -d brokerage
```

**Més comandes:** [ESTAT.md § Comandes ràpides](ESTAT.md)

---

## 7) Definition of Done / readiness gates

**Data Layer Gate 0 (core):**
- duplicates=0
- ts_step_errors=0
- missing ≤ 1/24h
- max_gap_s ≤ 180
- stale=0

**Exec sanity (annex):** smoke 3×, e2e 3× positions_after=0, soak 10 min.

**Referència:** [docs/ESTAT.md](ESTAT.md)

