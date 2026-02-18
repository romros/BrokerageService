# Realtime DataLayer v1 — Estat

**Data:** 2026-02-18

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | ✅ | `docker compose -f ... up -d realtime_datalayer` |
| GET /health | ✅ | Via broker routes /api/v1/broker/health |
| GET /status | 🟡 | En curs (stats, retention, uptime) |
| Ostium ingest 24/7 | ✅ | OstiumCandleIngestService |
| Tick recorder | ✅ | OstiumTickRecorder (opt-in) |
| Storage candles | ✅ | datafiles/realtime_datalayer/candles (configurable) |
| Storage ticks | ✅ | lab/out/ostium_forensics o REALTIME_DATALAYER_ROOT/ticks |
| Retenció per hores | 🟡 | En curs (REALTIME_*_MAX_HOURS) |
| Tests curts | ✅ | ./scripts/run_tests.sh realtime_datalayer |

---

## Comandes canòniques

```bash
# Arrencar servei
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer

# Verificar
curl -s http://localhost:8001/api/v1/broker/health
curl -s http://localhost:8001/status
curl -s http://localhost:8001/api/v1/broker/data_status

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer
```

---

## Tests

```bash
./scripts/run_tests.sh realtime_datalayer   # ràpid, 0-network
./test.sh testing/run_all.py                # full suite (només milestones)
```
