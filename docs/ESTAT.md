# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-16  
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
- ✅ **venue=paper** (zero tx): `MODE=paper` o `ENABLE_LIVE_TRADING=0` → PaperVenueAdapter, market data mainnet, execució simulada
- 🟡 **gTrade**: existent (paper OK); no prioritzat MVP; futur
- ⛔ **Backtest**: pendent

**DONE (sanity):** `run_all` OK + smoke 3× OK + e2e 3× OK (paper testnet) + **soak 10 min** OK + **WS soak 15 min** OK + **WS soak 15 min MAINNET EURUSD** OK (via Lighter feed real) + **Freqtrade paper 15 min** OK (venue=paper, positions_after=0) + **Paper soak real 120 min** OK (preus Lighter, positions_after=0, missing_minutes=0)

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

**2026-02-16**

| Run | Resultat | Log |
|-----|----------|-----|
| **Freqtrade paper 15 min** (venue=paper, fake feed) | ✅ open→position_pnl→close OK positions_after=0 candles=15 | `datafiles/freqtrade_runs/20260215_001044_ETH_15m.log` |
| **Fix 429 rate-limit** (LIVE testnet) | ✅ close OK malgrat 429; fallback cache/positions_mark | Evidència run_freqtrade_live_testnet.sh 15 min |
| **Paper soak real 120 min** | ✅ positions_after=0 missing_minutes=0 market_data_source=real candles=219 | `datafiles/freqtrade_runs/20260215_074407_ETH_120m_real.log` — latency_ohlcv_p95=17.8ms, latency_close_p95=6.4ms |

**2026-02-15**

| Run | Resultat | Log |
|-----|----------|-----|
| `testing/run_all.py` | ✅ 49 passed | — |
| **WS Soak 15 min** (fake feed) | ✅ candles=15 status=OK | `datafiles/ws_soak/20260214_011714_ws_soak_15m.log` |
| **WS Soak 15 min MAINNET EURUSD** (Lighter real) | ✅ candles=15 status=OK missing_minutes=0 | `datafiles/ws_soak/20260214_071609_ws_soak_15m_mainnet.log` |
| **P1.1 SL/TP idempotència** | ✅ test_sltp_idempotency, test_lighter_adapter_sltp (8 tests) | reducció risc duplicació SL/TP en retries/restarts |
| **P1.2 maker-first close** | ✅ test_close_maker_first (4 unit), test_close_position_maker_fallback_positions_after_zero (integration) | millor control de sortida i menys risc de slippage en closes |
| **PAPER DONE handshake** | ✅ freqtrade_runner.py, test_freqtrade_runner_short (skip si no .env) | Freqtrade-first: candles + price + open/close via HTTP, positions_after=0 |
| **GET /positions + PnL** | ✅ mark_price, unrealized_pnl a PositionItem | Veure com va la posició des de l'API sense calcular manualment |
| **freqtrade_runner position_pnl** | ✅ --position-poll-s 30 (per defecte) | Cada 30s consulta GET /positions i loga mark_price, unrealized_pnl |
| **freqtrade_runner closed_pnl** | ✅ després del close | GET /trades → close trade → calcula realized_pnl ($ i %) per comparar amb web; fix Lighter market_id→symbol |
| **GET /mode market_data_source** | ✅ fake\|real\|n/a | Visible al freqtrade_runner per saber si preus són fake (3500 base) o reals (Lighter API). Evita confusió mark_price 3695 vs Lighter 2085. |
| **Paper amb preus reals** | ✅ USE_FAKE_PRICE_FEED=0 + .env | Preus de Lighter mainnet (~2088$ ETH). Execució segueix sent simulada (zero tx). Evidència: mark_price 2087-2094, positions_after=0. |
| **position_id fallback** | ✅ freqtrade_runner | Si open no retorna position_id, s'obté de GET /positions per poder tancar. |
| **Evidència testnet PAPER** | ✅ múltiples runs 15 min | freqtrade_runner ETH 15m: open→position_pnl cada 30s→close→positions_after=0. Trade History web: PnL verificat ($3.80, -$3.26, $2.29) coincideix amb càlcul (open_price, close_price, size). Logs: `datafiles/freqtrade_runs/20260214_*_ETH_15m.log` |

**2026-02-13**

| Run | Resultat | Log |
|-----|----------|-----|
| Smoke 3× (lighter, 120s) | ✅ ok=3 failed=0 | `datafiles/smoke_runs/2026-02-13_154710_lighter_3x.log` |
| E2E trade 3× (ETH, 100 USDC, 20x) | ✅ positions_after=0 | `datafiles/e2e_runs/2026-02-13_*_lighter_ETH.log` |
| Soak 10 min (lighter, PAPER) | ✅ status=OK failed=0 | `datafiles/smoke_runs/soak_20260213_212644.log` |

---

## Paper soak real (preus Lighter)

Soak llarg amb PAPER (zero tx) i preus reals per validar estabilitat abans de Data Layer:

```bash
# Soak 2h (mínim), 6h o 12h
./scripts/soak_freqtrade_paper_real.sh 120   # 2h
./scripts/soak_freqtrade_paper_real.sh 360   # 6h
./scripts/soak_freqtrade_paper_real.sh 720   # 12h
```

**Requisits:** `.env` amb credencials Lighter. **Health gate:** exit 2 (positions_after!=0), 3 (missing_minutes>1), 4 (market_data_source!=real). **Log:** `datafiles/freqtrade_runs/<ts>_ETH_<N>m_real.log`

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

# PAPER DONE handshake (requereix broker + pipeline; test skip si no Lighter .env)
./test.sh testing/integration/test_freqtrade_runner_short.py
# Broker ha d'estar en marxa amb VENUE=lighter (adapter per open/close)
VENUE=lighter docker compose up -d brokerage
docker compose run --rm brokerage python3 -m application.tools.freqtrade_runner --venue lighter --mode PAPER --symbol ETH --minutes 15

# venue=paper (zero tx, sense Lighter): VENUE=paper + MODE=paper + ENABLE_LIVE_TRADING=0
./test.sh testing/integration/test_freqtrade_runner_short_paper.py
./scripts/run_freqtrade_paper.sh 3   # 3 min (script espera broker + executa runner)
# Paper amb preus FAKE (sense .env): USE_FAKE_PRICE_FEED=1
MODE=paper VENUE=paper ENABLE_LIVE_TRADING=0 USE_FAKE_PRICE_FEED=1 SYMBOLS=ETH,BTC docker compose up -d brokerage
# Paper amb preus REALS (cal .env Lighter): USE_FAKE_PRICE_FEED=0, mark_price ~2088$
MODE=paper VENUE=paper ENABLE_LIVE_TRADING=0 USE_FAKE_PRICE_FEED=0 SYMBOLS=ETH,BTC LIGHTER_SYMBOLS=ETH,BTC docker compose up -d brokerage
# Esperar ~10s; després (host.docker.internal evita NameResolutionError):
docker compose run --rm brokerage python3 -m application.tools.freqtrade_runner \
  --broker-url http://host.docker.internal:8000 --venue paper --symbol ETH --minutes 15

# LIVE testnet (tx reals, comparar preus/PnL amb web):
./scripts/run_freqtrade_live_testnet.sh 15   # 15 min
# Manual: MODE=live VENUE=lighter ENABLE_LIVE_TRADING=1 MARKET_DATA_ENV=testnet docker compose up -d brokerage
# Després: freqtrade_runner --venue lighter --symbol ETH --minutes 15
# Comparar: mark_price, unrealized_pnl, realized_pnl del log vs testnet.app.lighter.xyz Trade History

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
* ~~PAPER DONE handshake~~ ✅ freqtrade_runner.py (client HTTP pur) + test_freqtrade_runner_short; AGENTS §2.6

### P2

* ~~Safety runbook~~ ✅ docs/SAFETY_RUNBOOK.md + scripts/soak_smoke.sh
* ~~Soak 10 min~~ ✅ soak_20260213_212644.log (10 ticks, status=OK)
* ~~P2.0 WS Soak Preflight~~ ✅ pipeline al lifespan (VENUE=lighter, MODE in paper/live), ws_preflight.py, test_ws_preflight_contract
* ~~P2.0.1 Fake price feed + WS preflight integració~~ ✅ USE_FAKE_PRICE_FEED=1, test_ws_preflight_integration_real (broker real, fake feed, sense xarxa)
* ~~Soak WS 15 min / telemetria (P2.1)~~ ✅ ws_soak.py, scripts/soak_ws.sh, docker-compose.soak.yml, evidència 20260214_011714 (15 candles, status=OK)
* ~~P2.2 WS soak 15 min mainnet (real feed)~~ ✅ scripts/soak_ws_mainnet.sh, autodetect, EURUSD/XAU (docker-compose.mainnet-eurusd.yml), evidència 20260214_071609
* ~~market_data_source + paper preus reals~~ ✅ GET /mode market_data_source (fake|real), freqtrade_runner ho mostra; paper amb USE_FAKE_PRICE_FEED=0 → preus ~2088$; position_id fallback
* ~~Fix Lighter 429 rate-limit~~ ✅ PriceSnapshotCache compartit (candle pipeline, GET /price, close); 429 retry amb backoff; fallback cache stale / positions_mark; logs price_source; PRICE_CACHE_TTL_S, PRICE_STALE_MAX_S, PRICE_FETCH_DEADLINE_S
* Normalització addresses checksum

---

## Arxiu

**Històric complet (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md) — milestones, invariants Lighter, notes gTrade openPrice, historial detallat, definició DONE.
