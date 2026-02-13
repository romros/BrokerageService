# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-13  
**Repo/Path:** /mnt/volume-SQ/dev/BrokerageService  
**Venues:** **Lighter (principal)** · gTrade (existent)  
**Modes:** LIVE / PAPER / BACKTEST  
**Timeframe:** 1m only  
**TZ canònica:** America/New_York  
**Doc d'arquitectura:** AGENTS_ARQUITECTURA.md (minimalista, SOLID + DI, 3 modes)

---

## 0) TL;DR (lectura en 30s)

- ✅ **Lighter**: trading core + marketdata pipeline + **SL/TP + balance** complet (paper-ready).  
- ✅ **M2 tests Lighter SL/TP + Balance** passen (integration).  
- ✅ **Zero regressions** en el que s'ha tocat: suite rellevant passa.  
- 🟡 **Pendents (hardening / completitud IVenueAdapter)**: trade history, maker-first close (opcional), criteri "LIVE-ready" complet; **reconcile (detect/report ✅ + auto-repair v1 ✅)**.  
- 🟡 **gTrade**: paper i infra testnet/e2e preparada; mainnet hardening pendent (fees/reconcile/monitoring).

---

## 1) Estat actual (canònic)

### 1.1 Lighter (Venue Principal) — Estat
**Status:** ✅ Paper-ready (core complet) · 🟡 Live-hardening pendent · ⛔ Backtest pendent  

**Capacitats clau:**
- ✅ Market data: `get_pairs()`, `get_latest_price()`, polling ticks → candles 1m → CSV → WS
- ✅ Trading: `open_position()`, `close_position()`, `get_open_positions()`
- ✅ Risk/Account: `update_sl()`, `update_tp()`, `get_balance()`

**Última execució tests (confirmació):**
- `./test.sh testing/integration/test_lighter_adapter_sltp.py` → ✅ tot passa (update_sl/tp, scaling, reduce_only, balance, position_not_found)

### 1.2 gTrade (Venue Existent) — Estat
**Status:** ✅ Paper-ready · 🟡 Live-hardening pendent · ⛔ Backtest pendent  

**Notes:**
- Integració read/ops amb harness de seguretat i E2E testnet preparat.
- "OpenPrice" i temes de preus/oracle són **zona delicada** (veure secció 6).

---

## 2) Milestones (estables) + mapping a tasks (intern)

> Regla: **Milestones** són el que mireu sovint.  
> Les "tasks" (4A, 4B, 6B.1.B.7, etc.) es mantenen aquí com a mapping, però no governen l'estat.

| Milestone | Mode | Objectiu | Estat | Evidència |
|---|---|---|---|---|
| **M1** | PAPER | Lighter marketdata pipeline: ticks → 1m candles → CSV → WS | ✅ | `test_lighter_ticks_to_candles_flow.py` passing |
| **M2** | PAPER | Lighter SL/TP + Balance (paper-ready) | ✅ | `test_lighter_adapter_sltp.py` passing |
| **M3** | LIVE | Lighter "LIVE-ready hardening" (reconcile + persistència/lookup + criteri Done) | 🟡 | detect/report ✅ + auto-repair v1 (stale+resync) ✅; tests passing |
| **G1** | PAPER | gTrade paper + infra (done) | ✅ | suite estable |
| **G2** | LIVE | gTrade mainnet hardening (fees reals + reconcile + monitoring) | 🟡 | pendent |

**Mapping intern (històric):**
- Lighter: TASK 2 ✅ + TASK 3 ✅ + TASK 4A ✅ + TASK 4B ✅ + **M1 ✅ + M2 ✅**
- gTrade: fases 1 → 6B.1.B.7 ✅ (infra + harness), però mainnet hardening encara 🟡

---

## 3) Qualitat (Quality Gates)

### Gate A — Sense regressions (bloquejador)
- ✅ L'ecosistema de tests rellevant passa (incloent Lighter M2 integration).
- **Evidència:** `./test.sh testing/run_all.py` → ✅ (inclou `test_reconcile_service.py` des de M3).  
  - **Run date:** *(posar aquí la data/hora del darrer run_all; si no és avui: "run_all no executat avui")*

### Gate B — Tests core Lighter (bloquejador)
- ✅ Tests de SL/TP + Balance passen.
- ✅ Invariants crítics coberts (claus, scaling, reduce_only, idempotency) via unit/integration.

### Gate C — E2E / Smoke (post-milestone)
- 🟡 E2E/harness preparat; repetibilitat i criteri "LIVE-ready" pendent de formalitzar (veure backlog).

---

## 4) Backlog (únic lloc — prioritzat)

### P0 (bloqueja "LIVE-ready" de Lighter)
1. **Definir criteri "LIVE-ready"** (Done) per Lighter:
   - reconcile mínim (local vs venue)
   - **kill switch** (must-have): ex. `ENABLE_LIVE_TRADING=1` (0 = només paper/read)
   - **límits de risc** (must-have): ex. `MAX_OPEN_POSITIONS`, `MAX_NOTIONAL_USDC` (o per symbol)
   - **reconcile interval:** ex. `RECONCILE_INTERVAL_S`
   - logs/alerts mínims
2. **Reconcile loop (Lighter)**:
   - ✅ **detect/report:** ReconcileService cada `RECONCILE_INTERVAL_S`: compara venue vs local, ReconcileResult (missing_locally, extra_locally, mismatch), logs; tests unitaris passen.
   - ✅ **auto-repair v1:** build_actions → IReconcileSink.handle (MarkStalePosition + RequestResync); LoggingReconcileSink + IPositionTracker; tests test_reconcile_autorepair.py passen.
3. **Persistència / lookup SL/TP** (post-restart):
   - o bé persistir mapping local
   - o bé consultar ordres actives si l'API ho permet

### P1 (completitud IVenueAdapter / producte)
4. **Trade history** (si contracte ho exigeix): `get_trade_history()`
5. **Idempotència SL/TP** (si l'API externa ho demana)
6. **Maker-first close (opcional)**:
   - LIMIT POST_ONLY reduce_only + timeout + cancel + fallback MARKET

### P2 (polish / operativa)
7. Docs: "Safety runbook" (aturada, límits, monitoratge, incident)
8. Soak WS 120s / tuning polling/backfill
9. Normalització addresses checksum + petits refinaments

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

> Aquest bloc existeix per no perdre el context, però **no governa** l'estat diari.

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
```

---

## 8) Evidència recent (log / test run)

**2026-02-13**

Integration Tests — Lighter SL/TP + Balance (M2):

* ✓ test_update_sl_ok
* ✓ test_update_tp_ok
* ✓ test_update_sl_reduce_only_and_scaling
* ✓ test_update_tp_reduce_only_and_scaling
* ✓ test_get_balance_ok
* ✓ test_update_sl_position_not_found
* ✅ All M2 SL/TP + Balance tests passed

Unit tests — ReconcileService (M3 detect/report):

* ✓ no_diff, missing_locally, extra_locally, mismatch (symbol/size/is_long), loop interval (sleep_fn), config env
* ✅ `./test.sh testing/unit/test_reconcile_service.py` passen

Unit tests — Reconcile auto-repair v1 (M3.1):

* ✓ build_actions: no_diff, extra_locally, mismatch, missing_locally
* ✓ LoggingReconcileSink: mark_stale once (extra_locally), reason with fields (mismatch)
* ✓ no_diff -> handle not called; loop triggers sink.handle (sleep_fn)
* ✅ `./test.sh testing/unit/test_reconcile_autorepair.py` passen

---

## 9) Historial (changelog curt, dins el mateix fitxer)

> Regla: 1 línia per entrega important (data + què + resultat).

* **2026-02-12** — Lighter TASK2 ✅ (config + skeleton + invariants + tests)
* **2026-02-12** — Lighter TASK3 ✅ (market data client + mappers + get_pairs/get_latest_price)
* **2026-02-12** — Lighter TASK4A ✅ (open_position)
* **2026-02-12** — Lighter TASK4B ✅ (close_position + get_open_positions)
* **2026-02-12** — **M1 ✅** (ticks→candles→CSV→WS) *(commit: —)*
* **2026-02-13** — **M2 ✅** (SL/TP + Balance) + integration tests passant *(commit: —)*
* **2026-02-12** — Reconcile loop (detect/report): ReconcileService + ReconcileResult/PositionMismatch + tests unitaris *(commit: —)*
* **2026-02-12** — M3.1 auto-repair v1 (stale + resync): ReconcileAction, IPositionTracker, IReconcileSink, LoggingReconcileSink, build_actions; tests passen *(commit: —)*

---

## 10) Definició "DONE" recomanada (per evitar refactors que trenquin l'estat)

### DONE per Milestone (exemple M3 "LIVE-ready")

* [ ] reconcile loop mínim implementat i testejat
* [ ] kill switch clar (`ENABLE_LIVE_TRADING`)
* [ ] límits de risc (`MAX_OPEN_POSITIONS`, `MAX_NOTIONAL_USDC`) enforce
* [ ] interval reconcile (`RECONCILE_INTERVAL_S`) actiu i controlable
* [ ] alert/logging mínim (errors classificats)
* [ ] 3 runs "smoke" consecutius sense incidències (testnet si aplica)

---

**Status global:** ✅ Lighter paper-ready (M1+M2) · 🟡 hardening live · 🟡 gTrade mainnet hardening · ⛔ backtest pendent
