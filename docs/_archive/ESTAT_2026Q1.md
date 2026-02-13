# ESTAT DEL PROJECTE — BrokerageService (Archive Snapshot 2026-Q1, fins 2026-02-13)

> **Read-only.** Històric complet fins 2026-02-13. Estat actual → `ESTAT.md`.
>
> **Nota:** Aquest arxiu pot mencionar paths/docs legacy (ex. `/api/v1/ft`, `docs/BROKER_API.md`, `/broker/*`). La font canònica actual és `AGENTS_ARQUITECTURA.md` (API `/api/v1/broker/*`).

---

## 0) TL;DR (lectura en 30s)

- ✅ **Lighter**: trading core + marketdata pipeline + **SL/TP + balance** complet (paper-ready).  
- ✅ **M2 tests Lighter SL/TP + Balance** passen (integration).  
- ✅ **M3 LIVE-ready Lighter**: reconcile (detect/report + auto-repair v1) + LIVE guards + restart safety (bootstrap + SL/TP store) + smoke runner (M3.4) + smoke repeat (M3.5) + lifecycle hardening (M3.5.1); **3x smoke real executat**; zero warnings "Account not found" (fix AccountApi Configuration).  
- ✅ **M3.6** Real Paper E2E trade (Lighter testnet): P0.1+P0.2+P0.3 **DONE** — close loop + force_close_remaining + **3× E2E consecutius OK** (positions_after=0 cada run).
- ✅ **Zero regressions**: suite 43 tests passa (unit + integration mock; API smoke localhost).  
- ✅ **Broker API canònic**: REST endpoints `/api/v1/broker/*` (health, mode, venues, pairs, price, candles, balance, positions, orders/open, orders/close); només POST body per ordres; test_broker_api.py a run_all.
- 🟡 **Pendents (completitud IVenueAdapter)**: trade history, maker-first close (opcional).  
- 🟡 **gTrade**: paper i infra testnet/e2e preparada; mainnet hardening pendent (fees/reconcile/monitoring).

---

## 1) Estat actual (canònic)

### 1.1 Lighter (Venue Principal) — Estat
**Status (a 2026-02-13):** ✅ Paper-ready · ✅ Live-hardening complet · ⛔ Backtest pendent  

**Capacitats clau:**
- ✅ Market data: `get_pairs()`, `get_latest_price()`, polling ticks → candles 1m → CSV → WS
- ✅ Trading: `open_position()`, `close_position()`, `get_open_positions()`
- ✅ Risk/Account: `update_sl()`, `update_tp()`, `get_balance()`

**Última execució tests (confirmació):**
- `./test.sh testing/integration/test_lighter_adapter_sltp.py` → ✅ tot passa (**mock**: signer + account API; update_sl/tp, scaling, reduce_only, balance, position_not_found)

### 1.2 gTrade (Venue Existent) — Estat
**Status:** ✅ Paper-ready · 🟡 Live-hardening pendent · ⛔ Backtest pendent  

**Notes:**
- Integració read/ops amb harness de seguretat i E2E testnet preparat.
- "OpenPrice" i temes de preus/oracle són **zona delicada** (veure secció 6).

---

## 2) Milestones (estables) + mapping a tasks (intern)

| Milestone | Mode | Objectiu | Estat | Evidència |
|---|---|---|---|---|
| **M1** | PAPER | Lighter marketdata pipeline: ticks → 1m candles → CSV → WS | ✅ | `test_lighter_ticks_to_candles_flow.py` (mock) passing |
| **M2** | PAPER | Lighter SL/TP + Balance (paper-ready) | ✅ | `test_lighter_adapter_sltp.py` (mock) passing |
| **M3** | LIVE | Lighter "LIVE-ready hardening" (reconcile + persistència/lookup + criteri Done) | ✅ | detect/report ✅ + auto-repair v1 ✅ + LIVE guards ✅ + restart safety (bootstrap + SL/TP store) ✅ + smoke runner (M3.4) ✅ + smoke repeat (M3.5) ✅ + lifecycle hardening (M3.5.1) ✅; tests (mock) passing; **3x smoke real executat** |
| **G1** | PAPER | gTrade paper + infra (done) | ✅ | suite estable |
| **G2** | LIVE | gTrade mainnet hardening (fees reals + reconcile + monitoring) | 🟡 | pendent |

**Mapping intern (històric):**
- Lighter: TASK 2 ✅ + TASK 3 ✅ + TASK 4A ✅ + TASK 4B ✅ + **M1 ✅ + M2 ✅**
- gTrade: fases 1 → 6B.1.B.7 ✅ (infra + harness), però mainnet hardening encara 🟡

---

## 3) Qualitat (Quality Gates)

### Tests: mock vs real (referència ràpida)
- **Unit tests** (run_all.py): tots **mock** (sense xarxa ni venue real): candle_store, gap_validator, reconcile_service, live_guards, bootstrap_service, sltp_persistence, smoke_runner, smoke_repeat (M3.5), smoke_runner_lifecycle (M3.5.1), e2e_trade (M3.6), lighter scaling/order_builder/idempotency/key_manager, gtrade parser/chain_config/tx_sender, etc.
- **Integration Lighter** (M1/M2): **mock** — adapter/signer/account API mockejats (zero network): `test_lighter_ticks_to_candles_flow.py` (FakeLighterPriceFeedClient), `test_lighter_adapter_sltp.py` (DummySignerSLTP + fake account), `test_lighter_adapter_open/close/prices` (mocked signer/market data).
- **Integration gTrade**: **mock** — Web3/RPC mockejat: `test_gtrade_adapter_readonly.py`, `test_gtrade_adapter_write_mocked.py`; altres backfill/flow poden usar fixtures o mock.
- **API smoke** (test_rest_smoke, test_ws_smoke): **real localhost** — fan HTTP/WS a localhost; test_rest_smoke pot arrencar el servei en subprocess; test_ws_smoke espera servei en marxa (port configurable).
- **Smoke runner** (`application.smoke`): **--venue mock** = tot mock; **--venue lighter** = adapter/API Lighter **reals** (testnet/config env).

### Gate A — Sense regressions (bloquejador)
- ✅ L'ecosistema de tests rellevant passa (incloent Lighter M2 integration).
- **Evidència:** `./test.sh testing/run_all.py` → ✅ (Passed: 43 | Failed: 0 | unit + integration **mock**; inclou test_broker_api, test_smoke_runner, test_smoke_repeat, test_smoke_runner_lifecycle, test_lighter_adapter_close).  
  - **Run date:** 2026-02-13 (post P1 #4 Freqtrade connector)

### Gate B — Tests core Lighter (bloquejador)
- ✅ Tests de SL/TP + Balance passen.
- ✅ Invariants crítics coberts (claus, scaling, reduce_only, idempotency) via unit/integration.

### Gate C — E2E / Smoke (post-milestone)
- ✅ Smoke runner M3.4 disponible (Docker: `docker compose run --rm brokerage python3 -m application.smoke --venue mock|lighter --seconds N`; exit 0/1, logs interval_sec + "Smoke result: OK|FAILED").
- ✅ **M3.5** Smoke repeat: `--repeat N`, `--pause-s`, `--log-path`; output canònic `SMOKE_RESULT` / `SMOKE_SUMMARY`; log a `datafiles/smoke_runs/` (auto si `--repeat`>1). Test unitari `test_smoke_repeat.py` (mock).
- ✅ **M3.5.1** Lifecycle hardening: adapter start/stop per-run (try/finally), mode=paper coherent, zero resource leaks; test_smoke_runner_lifecycle.py (mock).
- ✅ **M3.6** Real Paper E2E "Trading sanity": `e2e_trade` open→close flux; CLI `--venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20`; output canònic `E2E_TRADE step=... status=OK|FAILED`; position_id canònic `lighter:{pair_id}` (contracte estable); `--log-path` o default `datafiles/e2e_runs/<ts>_<venue>_<symbol>.log`; test_e2e_trade.py (adapter fake).
- ✅ **M3.6.2** Settle wait robust: `_wait_until_flat()` després de close; `--settle-timeout-s` (default 120), `--poll-s` (default 2); force_close_remaining si timeout; FAIL amb dump si retry falla; test_e2e_settle_delayed, test_e2e_settle_timeout.
- ✅ **Contracte position_id**: `lighter:{pair_id}`; close per market (com lab close_open_position.py); no depèn d'idx volàtil.
- ✅ **Evidència 3× E2E trade real:** 3 runs consecutius (venue=lighter, mode=PAPER, symbol=ETH) — **tots OK**, positions_after=0 cada run. P0.1+P0.2+P0.3 DONE.
- ✅ **Evidència 3x real:** 3 smoke runs consecutius (venue=lighter, mode=PAPER, seconds=120) el 2026-02-13 15:47 — log: `/datafiles/smoke_runs/2026-02-13_154710_lighter_3x.log` — exit 0, SMOKE_SUMMARY: runs=3 ok=3 failed=0, zero resource leaks; fix AccountApi: zero warnings "Account not found".

---

## 4) Backlog (únic lloc — prioritzat)

### P0 (bloqueja "sanity real DONE" i "LIVE-ready")

**P0 E2E — Sanity real robust (ordre prioritzat):**

| P0 | Què | Estat |
|----|-----|-------|
| **P0.1** | close_position() idempotent contra parcials: mida real API, loop poll+retry fins flat, chunking 0.1 ETH si rebutjat | ✅ Implementat |
| **P0.2** | E2E: si positions_after≠0 al timeout, force_close_remaining() + tornar a esperar; --settle-timeout-s 120 default | ✅ Implementat |
| **P0.3** | Evidència: 3× E2E consecutius (com smoke repeat); log canònic | ✅ Passat |

**P0 LIVE-ready (existents):**
1. **Definir criteri "LIVE-ready"** (Done) per Lighter:
   - reconcile mínim (local vs venue)
   - ✅ **kill switch enforce:** `ENABLE_LIVE_TRADING=1` (0 = només paper/read); guards abans d'open_position.
   - ✅ **risk limits enforce:** `MAX_OPEN_POSITIONS`, `MAX_NOTIONAL_USDC`; application/services/live_guards.py + test_live_guards.py.
   - ✅ **reconcile interval:** `RECONCILE_INTERVAL_S` wired end-to-end (config → ReconcileService; smoke runner).
   - ✅ **logs/alerts mínims:** INFO/WARNING/ERROR; smoke error_count → exit 1, "Smoke result: OK|FAILED" (M3.4).
2. **Reconcile loop (Lighter)**:
   - ✅ **detect/report:** ReconcileService cada `RECONCILE_INTERVAL_S`: compara venue vs local, ReconcileResult (missing_locally, extra_locally, mismatch), logs; tests unitaris passen.
   - ✅ **auto-repair v1:** build_actions → IReconcileSink.handle (MarkStalePosition + RequestResync); LoggingReconcileSink + IPositionTracker; tests test_reconcile_autorepair.py passen.
3. **Persistència / lookup SL/TP** (post-restart) ✅ M3.3:
   - **Bootstrap (M3.3a):** run_bootstrap(adapter, tracker) → venue.get_open_positions() → tracker.upsert; opcional mark_missing_stale, rehidratació SL/TP des del store; ReconcileService.start() pot rebre bootstrap_fn.
   - **SL/TP store (M3.3b Camí 1):** ISltpStore + JsonSltpStore; path default `datafiles_root/{venue}/sltp_store.json`, override `SLTP_STORE_PATH`; write atòmic + mkdir -p; persistit a update_sl/update_tp i open_position; bootstrap rehidrata des del store.

### P1 (completitud IVenueAdapter / producte)
4. **Broker API** (REST): ✅ API unificat `/api/v1/broker/*`; POST body per orders; docs `BROKER_API.md`; test_broker_api a run_all; WS candles opcional (pendent).
5. **Trade history** (si contracte ho exigeix): `get_trade_history()`
6. **Idempotència SL/TP** (si l'API externa ho demana)
7. **Maker-first close (opcional)**:
   - LIMIT POST_ONLY reduce_only + timeout + cancel + fallback MARKET

### P2 (polish / operativa)
8. Docs: "Safety runbook" (aturada, límits, monitoratge, incident)
9. Soak WS 120s / tuning polling/backfill
10. Normalització addresses checksum + petits refinaments

---

## 5) Invariants crítics (Lighter) — NO oblidar mai

### 5.1 Two-key authentication (DUES claus)
- **L1 wallet key (64 hex)**: per registrar/gestionar API key (admin puntual)
- **API trading key (80 hex)**: per signar ordres (cada trade)

### 5.2 Decimal scaling per tipus d'ordre (Invariant)
Redactat segons `infrastructure/venues/lighter/scaling.py` (**source of truth**):

- **Market:** `base_amount` ×**10_000**; `avg_execution_price` ×**100**  
  - via `acceptable_price_int(...)` (no ×1e6)
- **Limit:** size ×**10_000**, price ×**100**
- **SL/TP:** size ×**10_000**, `trigger_price` ×**100**, `exec_price` ×**100**

### 5.3 Reduce-only sempre a tancaments / SL/TP
- `reduce_only=True` en close i SL/TP
- direcció invertida correcta (long→ask, short→bid segons implementació)

### 5.4 Client Order Index (idempotència)
- Lighter usa `uint32` (0..4294967295)
- mapping a IdempotencyStore via `str(index)`

---

## 6) Notes tècniques delicades (gTrade "openPrice" i testnet)

- Tema bloquejant històric: `openPrice` pot revertir si no reflecteix preu real/oracle.
- Opcions resolució (si cal reactivar):
  - integrar feed preu real-time abans d'enviar tx
  - trobar endpoint públic d'oracle via contracte
  - hardcode temporal + validació manual (quick&dirty)

---

## 7) Comandes ràpides

```bash
# Suite general
./test.sh testing/run_all.py

# Lighter M2 (SL/TP + Balance)
./test.sh testing/integration/test_lighter_adapter_sltp.py

# Smoke runner (M3.4/M3.5)
docker compose run --rm brokerage python3 -m application.smoke --venue mock --mode PAPER --seconds 5   # mock
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 120  # real Lighter (env)
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 120 --repeat 3 --pause-s 5

# E2E trade (M3.6)
docker compose run --rm brokerage python3 -m application.e2e_trade --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20 --settle-timeout-s 120 --poll-s 2 --log-path datafiles/e2e_runs/latest.log
```

---

## 8) Evidència recent (log / test run)

**2026-02-13**

Integration Tests — Lighter SL/TP + Balance (M2) — **mock**:
* ✓ test_update_sl_ok, test_update_tp_ok, test_update_sl_reduce_only_and_scaling, test_update_tp_reduce_only_and_scaling, test_get_balance_ok, test_update_sl_position_not_found
* ✅ All M2 SL/TP + Balance tests passed

Unit tests — ReconcileService, auto-repair v1, LIVE guards, Restart safety (M3.3), Smoke runner (M3.4), Smoke repeat (M3.5), Smoke runner lifecycle (M3.5.1), E2E trade (M3.6 / M3.6.2) — **mock** — tots passen.

Smoke runner real (Lighter testnet) — **2026-02-13**:
* ✓ 3 runs consecutius (--venue lighter --mode PAPER --seconds 120 --repeat 3)
* ✓ SMOKE_SUMMARY: runs=3 ok=3 failed=0; log a datafiles/smoke_runs/
* ✓ mode=paper coherent; zero "Unclosed client session"; zero "Account not found"

---

## 9) Historial (changelog curt)

* **2026-02-12** — Lighter TASK2 ✅ (config + skeleton + invariants + tests)
* **2026-02-12** — Lighter TASK3 ✅ (market data client + mappers + get_pairs/get_latest_price)
* **2026-02-12** — Lighter TASK4A ✅ (open_position)
* **2026-02-12** — Lighter TASK4B ✅ (close_position + get_open_positions)
* **2026-02-12** — **M1 ✅** (ticks→candles→CSV→WS)
* **2026-02-13** — **M2 ✅** (SL/TP + Balance) + integration tests passant
* **2026-02-12** — Reconcile loop (detect/report): ReconcileService + ReconcileResult/PositionMismatch + tests unitaris
* **2026-02-12** — M3.1 auto-repair v1 (stale + resync): ReconcileAction, IPositionTracker, IReconcileSink, LoggingReconcileSink, build_actions; tests passen
* **2026-02-13** — M3.2 LIVE guards: kill switch (ENABLE_LIVE_TRADING) + risk limits (MAX_OPEN_POSITIONS, MAX_NOTIONAL_USDC); application/config, live_guards.py, routes; test_live_guards.py
* **2026-02-13** — M3.3 Restart safety: bootstrap, SL/TP store (ISltpStore, JsonSltpStore); test_bootstrap_service, test_sltp_persistence
* **2026-02-13** — M3.4 Smoke runner: run_smoke() bootstrap + reconcile loop, RECONCILE_INTERVAL_S end-to-end; test_smoke_runner.py
* **2026-02-13** — M3.5 Gate C repeat: --repeat N, --pause-s, --log-path; SMOKE_RESULT/SMOKE_SUMMARY; test_smoke_repeat.py
* **2026-02-13** — **M3.5.1 ✅** Smoke runner lifecycle hardening; **3x smoke real Lighter executat** → **M3 COMPLETAT ✅**
* **2026-02-13** — Fix: web3>=7.0.0 API change (`rawTransaction` → `raw_transaction`) en tx_sender.py
* **2026-02-13** — Fix AccountApi: ApiClient Configuration; elimina warnings "Account not found"
* **2026-02-13** — **M3.6** Real Paper E2E "Trading sanity": application/e2e_trade.py; test_e2e_trade.py (adapter fake)
* **2026-02-13** — **M3.6.1** Fix position_id canònic + evidence log
* **2026-02-13** — **M3.6.2** Settle wait robust: _wait_until_flat(), force_close_remaining; test_e2e_settle_delayed, test_e2e_settle_timeout
* **2026-02-13** — **Contracte position_id estable**: `lighter:{pair_id}`
* **2026-02-13** — **close_position fix (partial fills)**: mida real API, fallback chunks 0.1 ETH, loop poll fins flat
* **2026-02-13** — **Criteri sanity real DONE**: P0.1✅ P0.2/P0.3🟡
* **2026-02-13** — **P0.2 force_close_remaining**: e2e_trade si positions_after≠0 al timeout
* **2026-02-13** — **P0.3 DONE**: 3× E2E consecutius — tots OK, positions_after=0
* **2026-02-13** — **Tasca Freqtrade connector**: TASCA_FREQTRADE_CONNECTOR.md + docs/BROKER_API.md; P1 #4 backlog
* **2026-02-13** — **P1 #4 Freqtrade connector DONE**: freqtrade_routes.py (prefix /api/v1/ft), test_broker_api.py a run_all; 43 tests passen
* **2026-02-13** — **Unificació Broker API**: broker_routes.py (prefix /api/v1/broker); routes.py + freqtrade_routes eliminats; adapter_factory wiring a main; 43 tests passen
* **2026-02-13** — **Neteja API canònica**: open-q/close-q eliminats; només POST body per orders; IBrokerageService, Ostium, mapping Freqtrade eliminats del core; models estrictes; VENUE=lighter|none; ARQUITECTURA_REVIEW incorporat a AGENTS_ARQUITECTURA.md; test_broker_api.py (renom de test_freqtrade_api)

---

## 11) Tasca Freqtrade connector (P1 #4)

**Objectiu:** Integrar Freqtrade amb BrokerageService via REST + WS (IVenueAdapter + pipeline candles).

**Checklist:** 1) Contracte + API ✅ `docs/BROKER_API.md` · 3) Mapping a core (IVenueAdapter) · 4) Implementació ✅ (broker_routes.py, prefix `/api/v1/broker`) · 5) Tests ✅ (test_broker_api.py a run_all) · Gate: docs ✅ endpoints ✅ tests sense regressions ✅

**Endpoints mínims (canònics, POST body únic):** `GET /broker/health` · `GET /broker/mode` · `GET /broker/venues` · `GET /broker/pairs?venue=` · `GET /broker/price/latest?venue=&symbol=` · `GET /broker/candles` · `GET /broker/ohlcv/{symbol}` · `GET /broker/balance?venue=` · `GET /broker/positions?venue=` · `POST /broker/orders/open` (JSON body) · `POST /broker/orders/close` (JSON body) · WS candles (opcional, pendent)

**Fitxers:** `application/api/broker_routes.py`, `testing/unit/test_broker_api.py`, `testing/run_all.py`.

---

## 12) Definició "DONE" recomanada

* [x] reconcile loop mínim implementat i testejat
* [x] kill switch clar (`ENABLE_LIVE_TRADING`)
* [x] límits de risc (`MAX_OPEN_POSITIONS`, `MAX_NOTIONAL_USDC`) enforce
* [x] interval reconcile (`RECONCILE_INTERVAL_S`) actiu i controlable
* [x] alert/logging mínim
* [x] 3 runs "smoke" consecutius sense incidències

---

**Status global:** ✅ Lighter paper-ready (M1+M2) · ✅ Lighter LIVE-ready hardening (M3 completat; 3x smoke real) · ✅ **M3.6 sanity real fiable** (3× E2E real OK) · ✅ **P1 #4 Freqtrade connector** (REST endpoints + tests) · 🟡 gTrade mainnet hardening · ⛔ backtest pendent
