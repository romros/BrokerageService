# trading_service — Estat

**Data:** 2026-02-19

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | ✅ | `docker compose -f ... up -d trading_service` |
| GET /health | ✅ | Via broker routes |
| GET /balance, /positions, /trades | ✅ | Lighter MVP 100% |
| POST /orders/open, /close | ✅ | Guards + idempotència |
| Reconcile | ✅ | Operatiu |
| Consumeix realtime_datalayer | ✅ | Phase 2: HttpDataLayerReader + QualityGate fail-closed |
| Ingest propi | ✅ N/A | NO té ingest ni writer (per disseny) |
| Tests curts | 🟡 | `./scripts/run_tests.sh trading_service` |

---

## DoD del servei

- [ ] Ordres open/close funcionen correctament amb Lighter
- [x] Consumeix candles del realtime_datalayer (Phase 2: HttpDataLayerReader + QualityGate)
- [ ] Reconcile i guards operatius
- [ ] Tests de role wiring passen (no /orders en realtime_datalayer)

---

## Comandes canòniques

```bash
# Arrencar servei
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d trading_service

# Verificar
curl -s http://localhost:8010/api/v1/broker/health
curl -s http://localhost:8010/api/v1/broker/balance?venue=lighter
curl -s http://localhost:8010/api/v1/broker/positions?venue=lighter

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build trading_service

# Tests
./scripts/run_tests.sh trading_service
```

---

## Notes

- **Mode paper:** Per defecte `MODE=paper`. Live trading requereix `ENABLE_LIVE_TRADING=1` explícit.
- **Venue Lighter:** MVP 100% completat. gTrade i Ostium pendents.
- **Phase 2 (completada):** trading_service llegeix candles del realtime_datalayer via HTTP (`REALTIME_DATALAYER_BASE_URL`). `HttpDataLayerReader` + `QualityGateEvaluator` fail-closed. Si no configurat, usa data layer local.
