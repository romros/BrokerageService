# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-13  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venues:** **Lighter (principal)** · gTrade (existent)  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York`  
**TZ container (runtime/logs):** `TZ=America/New_York`  
**Doc referència:** [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)  
**Runbook operatiu:** [SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md)  
**Històric complet (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

**Recorda Docker:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`. Vegeu AGENTS_ARQUITECTURA.md §7.

---

## TL;DR

- ✅ **Lighter M1+M2+M3** DONE: marketdata, SL/TP, balance, reconcile, guards, bootstrap, smoke runner, e2e trade
- ✅ **3× smoke real** + **3× e2e trade real** (paper testnet) — `positions_after=0`
- ✅ **44 tests** passa (unit + integration mock + API smoke localhost); `test_broker_api` + `test_mode_market_data_env` a `run_all`
- ✅ **Broker API canònic** `/api/v1/broker/*` (POST body únic per ordres) — AGENTS §3
- ✅ **Freqtrade P0** PAPER mainnet-data: `MARKET_DATA_ENV`, `ENABLE_LIVE_TRADING`, wiring Lighter/gTrade, `GET /mode` → `market_data_env`
- 🟡 **gTrade**: paper OK; mainnet hardening pendent
- ⛔ **Backtest**: pendent

**DONE (sanity):** `run_all` OK + smoke 3× OK + e2e 3× OK (paper testnet) + **soak 10 min** OK

---

## PROGRÉS (vs objectiu final d'arquitectura)

> Objectiu final (AGENTS_ARQUITECTURA): servei amb **3 modes (LIVE/PAPER/BACKTEST)**, **API canònica**, pipeline de dades 1m, venues (Lighter principal + gTrade), qualitat (tests + evidència real), i hardening operatiu.

### Global
- **Core (PAPER + API + qualitat): 85%**
- **LIVE hardening (Lighter): 75%** *(paper testnet + guards/reconcile + evidència OK; falta operativa live real contínua)*
- **BACKTEST: 0–10%** *(contracte previst, pipeline pendent)*

### Per àrees (checklist)
| Àrea | Objectiu | Estat | % |
|---|---|---:|---:|
| Broker API | `/api/v1/broker/*`, POST body, errors consistents | ✅ | 100% |
| Market data | pairs + latest price (adapter) + candles/ohlcv (candle_store) | ✅ | 100% |
| Candles pipeline | 1m only, ts epoch UTC, TZ NY, store sense venue | ✅ | 95% |
| Lighter (PAPER) | open/close + SL/TP + balance + idempotència close | ✅ | 100% |
| Lighter (LIVE-hardening) | guards + reconcile + restart safety + smoke runner + evidència real | ✅ | 90% |
| gTrade (PAPER) | infra/harness paper estable | ✅ | 80% |
| gTrade (LIVE) | mainnet hardening (fees/reconcile/monitoring) | 🟡 | 30% |
| Backtest mode | lectura dataset + exec engine + controls | ⛔ | 0–10% |
| Operativa / Runbook | safety runbook, soak 10 min, tuning | ✅ | 40% |

> Nota: els % són "de producte" (completitud + evidència), no només "codi escrit".

---

## Evidència recent

**2026-02-13**

| Run | Resultat | Log |
|-----|----------|-----|
| `testing/run_all.py` | ✅ 44 passed | — |
| Smoke 3× (lighter, 120s) | ✅ ok=3 failed=0 | `datafiles/smoke_runs/2026-02-13_154710_lighter_3x.log` |
| E2E trade 3× (ETH, 100 USDC, 20x) | ✅ positions_after=0 | `datafiles/e2e_runs/2026-02-13_*_lighter_ETH.log` |
| **Soak 10 min** (lighter, PAPER) | ✅ status=OK failed=0 | `datafiles/smoke_runs/soak_20260213_212644.log` |

---

## Comandes ràpides

```bash
# Suite general (mock + API smoke)
./test.sh testing/run_all.py

# Lighter SL/TP + Balance (integration mock)
./test.sh testing/integration/test_lighter_adapter_sltp.py

# Smoke (Docker)
docker compose run --rm brokerage python3 -m application.smoke --venue mock --mode PAPER --seconds 5
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 120 --repeat 3 --pause-s 5

# E2E trade (Docker, paper testnet)
docker compose run --rm brokerage python3 -m application.e2e_trade \
  --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20 \
  --settle-timeout-s 120 --poll-s 2

# Soak smoke (10 min; veure SAFETY_RUNBOOK.md)
./scripts/soak_smoke.sh
# o 15 min: ./scripts/soak_smoke.sh 900
```

---

## Backlog (prioritzat)

### P0 — DONE

* P0.1 close_position idempotent contra parcials ✅
* P0.2 force_close_remaining si timeout ✅
* P0.3 Evidència 3× E2E consecutius ✅
* P0.4 Freqtrade PAPER mainnet-data (MARKET_DATA_ENV, wiring, GET /mode) ✅
* P0.5 Soak smoke 10 min (lighter, PAPER) ✅

### P1

* ~~trade history (IVenueAdapter)~~ ✅ P1 DONE — GET /trades, TradeFill, Lighter account_trades, gTrade stub
* idempotència SL/TP (si cal)
* maker-first close (opcional)

### P2

* ~~Safety runbook~~ ✅ docs/SAFETY_RUNBOOK.md + scripts/soak_smoke.sh
* ~~Soak 10 min~~ ✅ soak_20260213_212644.log (10 ticks, status=OK)
* Soak WS / tuning polling
* Normalització addresses checksum

---

## Arxiu

**Històric complet (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md) — milestones, invariants Lighter, notes gTrade openPrice, historial detallat, definició DONE.
