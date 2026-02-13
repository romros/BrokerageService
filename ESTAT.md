# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-13  
**Repo/Path:** /mnt/volume-SQ/dev/BrokerageService  
**Venues:** **Lighter (principal)** · gTrade (existent)  
**Doc referència:** [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md)  
**Històric complet:** [docs/_archive/ESTAT_2026Q1.md](docs/_archive/ESTAT_2026Q1.md)

**Recorda Docker:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`. Vegeu AGENTS_ARQUITECTURA.md §7.

---

## TL;DR

- ✅ **Lighter M1+M2+M3** DONE: marketdata, SL/TP, balance, reconcile, guards, bootstrap, smoke runner, e2e trade
- ✅ **3× smoke real** + **3× e2e trade real** (paper testnet) — positions_after=0
- ✅ **43 tests** passa (unit + integration mock + API smoke localhost); test_broker_api a run_all
- ✅ **Broker API canònic** `/api/v1/broker/*` (POST body únic per ordres)
- 🟡 **gTrade**: paper OK; mainnet hardening pendent
- ⛔ **Backtest**: pendent

---

## Evidència recent

**2026-02-13**

| Run | Resultat | Log |
|-----|----------|-----|
| run_all.py | ✅ 43 passed | — |
| Smoke 3× (lighter, 120s) | ✅ ok=3 failed=0 | `datafiles/smoke_runs/2026-02-13_154710_lighter_3x.log` |
| E2E trade 3× (ETH, 100 USDC, 20x) | ✅ positions_after=0 | `datafiles/e2e_runs/` |

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
```

---

## Backlog (prioritzat)

### P0 — DONE
- P0.1 close_position idempotent contra parcials ✅
- P0.2 force_close_remaining si timeout ✅
- P0.3 Evidència 3× E2E consecutius ✅

### P1
- trade history (IVenueAdapter)
- idempotència SL/TP (si cal)
- maker-first close (opcional)

### P2
- Safety runbook
- Soak WS / tuning polling
- Normalització addresses checksum

---

## Arxiu

**Històric complet:** [docs/_archive/ESTAT_2026Q1.md](docs/_archive/ESTAT_2026Q1.md) — milestones, invariants Lighter, notes gTrade openPrice, historial detallat, definició DONE.
