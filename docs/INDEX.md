# BrokerageService — Índex de documentació

**Data:** 2026-02-19
**Repo:** `/mnt/volume-SQ/dev/BrokerageService`

Hub canònic. Tota la navegació comença aquí.

---

## Projecte global

| Doc | Descripció |
|-----|------------|
| [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md) | Arquitectura general, split vNext, boundaries |
| [docs/ESTAT.md](ESTAT.md) | Estat del projecte, TL;DR, comandes canòniques |
| [docs/runbook_trades_api.md](runbook_trades_api.md) | API canònica trades (rutes, mode LIVE/PAPER, models) — T2 positions |
| [docs/SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md) | Runbook operatiu (guardes, riscos, rollback) |
| [docs/LAB_OSTIUM_PRICE_MONITORING.md](LAB_OSTIUM_PRICE_MONITORING.md) | Investigació tècnica monitoratge de preus Ostium |
| [docs/plantilla_tasca.md](plantilla_tasca.md) | Plantilla per definir tasques |
| [docs/DIAGNOSI_PROJECTE_2026-02.md](DIAGNOSI_PROJECTE_2026-02.md) | Diagnòsi arquitectura, objectius, operativa (2026-02) |

---

## Subprojectes (Split vNext)

### realtime_datalayer (port 8081)
Recollida 24/7 de preus (Ostium) i servei de candles/ticks recents. Servei autònom.

| Doc | Descripció |
|-----|------------|
| [apps/realtime_datalayer/realtime_datalayer_arquitectura.md](../apps/realtime_datalayer/realtime_datalayer_arquitectura.md) | Arquitectura: components, storage, API, market hours, HEALTH vs COVERAGE |
| [apps/realtime_datalayer/realtime_datalayer_estat.md](../apps/realtime_datalayer/realtime_datalayer_estat.md) | Estat actual, comandes canòniques, FAQs |

**Comandes ràpides:**
```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer
curl -s http://localhost:8081/health
curl -s http://localhost:8081/ui       # Dashboard web
./scripts/run_tests.sh realtime_datalayer
```

---

### historical_datalayer (port 8082)
Backfill Dukascopy, compat reports, stitching gated. Servei autònom.

| Doc | Descripció |
|-----|------------|
| [apps/historical_datalayer/historical_datalayer_arquitectura.md](../apps/historical_datalayer/historical_datalayer_arquitectura.md) | Arquitectura: backfill, compat, stitching, API |
| [apps/historical_datalayer/historical_datalayer_estat.md](../apps/historical_datalayer/historical_datalayer_estat.md) | Estat actual, DoD, comandes |

**Comandes ràpides:**
```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d historical_datalayer
curl -s http://localhost:8082/health
./scripts/run_tests.sh historical_datalayer
```

---

### trading_service (port 8010)
Execució d'ordres, balance, positions. Consumeix Data Layer per preu/candles.

| Doc | Descripció |
|-----|------------|
| [apps/trading_service/trading_service_arquitectura.md](../apps/trading_service/trading_service_arquitectura.md) | Arquitectura: adapters, routes, guards, reconcile |
| [apps/trading_service/trading_service_estat.md](../apps/trading_service/trading_service_estat.md) | Estat actual, DoD, comandes |

**Comandes ràpides:**
```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d trading_service
curl -s http://localhost:8010/api/v1/broker/health
./scripts/run_tests.sh trading_service
```

---

## Ostium LIVE (MVP)

**Source of truth:** [docs/ESTAT.md](ESTAT.md) § Ostium LIVE.

```bash
./scripts/up_ostium_live.sh
```

Smoke only: `./scripts/run_ostium_live_smoke.sh --recreate --clean`

---

## LAB (Experimental)

| Doc | Descripció |
|-----|------------|
| [lab/ostium/README.md](../lab/ostium/README.md) | Runbook Ostium LAB (E2E + neteja canònics), inventari scripts, path to prod |
| [lab/ostium/RESULTS.md](../lab/ostium/RESULTS.md) | Validació trading testnet (fees, multicall, open/close) |
| [docs/LAB_OSTIUM_PRICE_MONITORING.md](LAB_OSTIUM_PRICE_MONITORING.md) | Investigació tècnica compat Ostium vs Dukascopy |

---

## Tests

```bash
# Per subprojecte (ràpid, 0-network)
./scripts/run_tests.sh realtime_datalayer
./scripts/run_tests.sh historical_datalayer
./scripts/run_tests.sh trading_service
./scripts/run_tests.sh core

# Full suite (milestones)
./test.sh testing/run_all.py

# Smoke (servei + artefacte)
./scripts/run_smoke.sh realtime_datalayer
```

---

## Estructura del repo

```
BrokerageService/
├── apps/
│   ├── realtime_datalayer/    # Ingest 24/7, candles/ticks
│   ├── historical_datalayer/  # Backfill, compat, stitching
│   └── trading_service/       # Ordres, balance, positions
├── application/               # Shared: app_factory, services, data
├── packages/shared/           # Clients HTTP entre serveis
├── testing/                   # Tots els tests (0-network)
│   └── suites/                # Llistes de tests per suite
├── deploy/compose/            # Compose split vNext
├── docs/                      # Documentació global (aquí ets)
├── lab/ostium/                # LAB experimental Ostium
├── scripts/                   # run_tests.sh, run_smoke.sh, run_lab.sh
└── datafiles/                 # Dades persistents (volum Docker)
    └── realtime_datalayer/    # candles/, ticks/, config/
```

---

## Arxivat (docs/_archive/2026-03-04_docs_cleanup/)

| Doc | Motiu |
|-----|-------|
| LAB_LIGHTER_HISTORICAL.md | Lighter arxivat T5.32 |
| MODEL_FEES_LIGHTER.md | Lighter arxivat T5.32 |
| ARCH_REVIEW_P4_READY.md | Tasca P3.3 completada (històric) |
| RESUM_T9.15_2026-03-04.md | Evidència tasca; info a ESTAT/DATA_PARITY_GATES |
| RESUM_T9.19_decommission_2026-03-04.md | Evidència tasca; info a ESTAT/DATA_PARITY_GATES |
