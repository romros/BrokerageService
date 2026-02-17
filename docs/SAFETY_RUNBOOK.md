# Runbook operatiu curt — BrokerageService

**Objectiu:** Document que obres quan hi ha un incident. Procediments mínims per detectar i actuar.

**Docs:** [ESTAT.md](ESTAT.md) · [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)

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
curl -s http://localhost:8000/health
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

| Incident | Diagnòstic | Acció |
|----------|------------|-------|
| **Stale feed** (stale_seconds > X) | data_status, last_candle_ts | Restart pipeline; check upstream; mark degraded |
| **Missing minutes** | X-Data-Missing-Minutes, coverage | Activar read-through (serve-only); executar repair; no mutar primary |
| **Duplicates / ts_step_errors** | data_status, integrity | Hard stop (no declarar primary); investigar writer |
| **503 / pipeline down** | health, data_status | Restart; check logs |

---

## 4) Kill switches

| Variable | Efecte |
|----------|--------|
| `ENABLE_LIVE_TRADING=0` | Paper (zero tx). Default. |
| `ENABLE_LIVE_TRADING=1` | Permet execució real LIVE. |
| `USE_FAKE_PRICE_FEED=1` | Preus fake (sense xarxa). |
| `USE_FAKE_PRICE_FEED=0` | Preus reals (cal .env Lighter). |
| `ENABLE_READ_THROUGH=1` | Gap repair serve-only (no muta store). |

**On:** `.env` o `docker-compose.yml` environment.

**Guards:** `MAX_OPEN_POSITIONS`, `MAX_NOTIONAL_USDC` (veure `application/config/live_guards_config.py`).

**Reconcile:** ReconcileService compara posicions venue vs tracking. Diff → missing_locally, extra_locally. Logs: stdout; `datafiles/smoke_runs/` si smoke --repeat.

---

## 5) Recovery playbooks

| Situació | Acció |
|----------|-------|
| **Restart** | `docker compose down`; `docker compose up -d brokerage` |
| **Backfill / repair** | BackfillService (lifespan) + read-through (GET ohlcv si `ENABLE_READ_THROUGH=1`); test: `test_gap_repair_flow.py` (--include-lighter-backfill) |
| **Disable symbol** | Env: `SYMBOLS`, `LIGHTER_SYMBOLS`, `BACKFILL_SYMBOLS`; no policy registry per ara |
| **Degrade mode** | Fallback-only (no mixed); 422 mixed si compat FAIL |

---

## 6) Comandes essencials (10 línies)

```bash
./test.sh testing/run_all.py
curl -s http://localhost:8000/api/v1/broker/data_status
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2
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

