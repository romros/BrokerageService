# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-15  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venues:** **Lighter (principal — MVP 100%)** · gTrade (futur)  
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
- ✅ **50+ tests** passa (unit + integration mock + API smoke localhost); inclou `test_ws_preflight_contract` (P2.0), `test_ws_preflight_integration_real` (P2.0.1), `test_ws_soak_short` (P2.1), `test_close_maker_first` (P1.2)
- ✅ **Broker API canònic** `/api/v1/broker/*` (POST body únic per ordres) — AGENTS §3
- ✅ **Freqtrade P0** PAPER mainnet-data: `MARKET_DATA_ENV`, `ENABLE_LIVE_TRADING`, wiring Lighter/gTrade, `GET /mode` → `market_data_env`
- 🟡 **gTrade**: existent (paper OK); no prioritzat MVP; futur
- ⛔ **Backtest**: pendent

**DONE (sanity):** `run_all` OK + smoke 3× OK + e2e 3× OK (paper testnet) + **soak 10 min** OK + **WS soak 15 min** OK + **WS soak 15 min MAINNET EURUSD** OK (via Lighter feed real)

---

## PROGRÉS (vs objectiu final d'arquitectura)

> Objectiu final (AGENTS_ARQUITECTURA): servei amb **3 modes (LIVE/PAPER/BACKTEST)**, **API canònica**, pipeline de dades 1m. **MVP 100% Lighter**; altres DEX (gTrade, etc.) s’incorporaran en el futur.

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
| Lighter (PAPER) | open/close + SL/TP + balance + idempotència close + idempotència SL/TP (P1.1) + maker-first close (P1.2) | ✅ | 100% |
| Lighter (LIVE-hardening) | guards + reconcile + restart safety + smoke runner + evidència real | ✅ | 90% |
| gTrade (PAPER) | infra/harness paper estable | ✅ | 80% |
| gTrade (LIVE) | mainnet hardening (fees/reconcile/monitoring) | 🟡 | 30% |
| Backtest mode | lectura dataset + exec engine + controls | ⛔ | 0–10% |
| Operativa / Runbook | safety runbook, soak 10 min, WS soak 15 min, tuning | ✅ | 50% |

> Nota: els % són "de producte" (completitud + evidència), no només "codi escrit".

---

## Evidència recent

**2026-02-15**

| Run | Resultat | Log |
|-----|----------|-----|
| `testing/run_all.py` | ✅ 49 passed | — |
| **WS Soak 15 min** (fake feed) | ✅ candles=15 status=OK | `datafiles/ws_soak/20260214_011714_ws_soak_15m.log` |
| **WS Soak 15 min MAINNET EURUSD** (Lighter real) | ✅ candles=15 status=OK missing_minutes=0 | `datafiles/ws_soak/20260214_071609_ws_soak_15m_mainnet.log` |
| **P1.1 SL/TP idempotència** | ✅ test_sltp_idempotency, test_lighter_adapter_sltp (8 tests) | reducció risc duplicació SL/TP en retries/restarts |
| **P1.2 maker-first close** | ✅ test_close_maker_first (4 unit), test_close_position_maker_fallback_positions_after_zero (integration) | millor control de sortida i menys risc de slippage en closes |

**2026-02-13**

| Run | Resultat | Log |
|-----|----------|-----|
| Smoke 3× (lighter, 120s) | ✅ ok=3 failed=0 | `datafiles/smoke_runs/2026-02-13_154710_lighter_3x.log` |
| E2E trade 3× (ETH, 100 USDC, 20x) | ✅ positions_after=0 | `datafiles/e2e_runs/2026-02-13_*_lighter_ETH.log` |
| Soak 10 min (lighter, PAPER) | ✅ status=OK failed=0 | `datafiles/smoke_runs/soak_20260213_212644.log` |

---

## Comandes ràpides

```bash
# Suite general (mock + API smoke)
./test.sh testing/run_all.py

# Lighter SL/TP + Balance (integration mock)
./test.sh testing/integration/test_lighter_adapter_sltp.py

# P1.2 maker-first close (unit + integration)
./test.sh testing/unit/test_close_maker_first.py
./test.sh testing/integration/test_lighter_adapter_close.py

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

# WS Soak (P2.1): 15 min, valida pipeline candles via WS
# Broker amb pipeline: docker compose -f docker-compose.yml -f docker-compose.soak.yml up -d
./scripts/soak_ws.sh        # 15 min
./scripts/soak_ws.sh 900    # 15 min
./scripts/soak_ws_quick.sh  # test ràpid 60s

# WS Soak MAINNET (P2.2): 15 min, Lighter real feed
# Requereix: .env amb credencials Lighter
./scripts/soak_ws_mainnet.sh        # 15 min
./scripts/soak_ws_mainnet.sh 900    # 15 min

# WS Soak: OHLCV visible al log (O, H, L, C, V per candle)
# Per EURUSD/XAU (Lighter): docker-compose.mainnet-eurusd.yml + --topic candle:EURUSD:1m
docker compose run --rm brokerage python3 -m application.tools.ws_soak \
  --minutes 1 --autodetect-symbols --venue lighter   # Lighter (ETH/BTC)
docker compose run --rm brokerage python3 -m application.tools.ws_soak \
  --minutes 1 --topic candle:EURUSD:1m              # EURUSD (si broker té pipeline gTrade)
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
* ~~Coding standards~~ ✅ constants canòniques (foundation/config, error_codes), zero hardcode a broker_routes (AGENTS §2.4)
* ~~idempotència SL/TP (si cal)~~ ✅ P1.1 DONE — idempotency key, persistència order indices, cancel no-op, logs sltp_*
* ~~maker-first close (opcional)~~ ✅ P1.2 DONE — limit reduce-only + timeout + fallback market; logs close_path/close_final; millor control de sortida i menys risc de slippage

### P2

* ~~Safety runbook~~ ✅ docs/SAFETY_RUNBOOK.md + scripts/soak_smoke.sh
* ~~Soak 10 min~~ ✅ soak_20260213_212644.log (10 ticks, status=OK)
* ~~P2.0 WS Soak Preflight~~ ✅ pipeline al lifespan (VENUE=lighter, MODE in paper/live), ws_preflight.py, test_ws_preflight_contract
* ~~P2.0.1 Fake price feed + WS preflight integració~~ ✅ USE_FAKE_PRICE_FEED=1, test_ws_preflight_integration_real (broker real, fake feed, sense xarxa)
* ~~Soak WS 15 min / telemetria (P2.1)~~ ✅ ws_soak.py, scripts/soak_ws.sh, docker-compose.soak.yml, evidència 20260214_011714 (15 candles, status=OK)
* ~~P2.2 WS soak 15 min mainnet (real feed)~~ ✅ scripts/soak_ws_mainnet.sh, autodetect, EURUSD/XAU (docker-compose.mainnet-eurusd.yml), evidència 20260214_071609
* Normalització addresses checksum

---

## Arxiu

**Històric complet (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md) — milestones, invariants Lighter, notes gTrade openPrice, historial detallat, definició DONE.
