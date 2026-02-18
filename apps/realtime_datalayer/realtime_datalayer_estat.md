# Realtime DataLayer v1 — Estat

**Data:** 2026-02-18

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | ✅ | `docker compose -f ... up -d realtime_datalayer` |
| GET /health | ✅ | Via broker routes /api/v1/broker/health |
| GET /status | ✅ | stats, retention, uptime |
| GET/PUT /symbols | ✅ | Hot-reload símbols sense restart |
| Instrument resolution | ✅ | spot/perp, override a config |
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
curl -s http://localhost:8001/health
curl -s http://localhost:8001/status
curl -s http://localhost:8001/symbols
curl -s http://localhost:8001/api/v1/broker/data_status

# UI i docs (túnel: ssh -L 8001:localhost:8001 user@host)
# Obrir al navegador: http://localhost:8001/ui  i  http://localhost:8001/docs

# Canviar símbols sense restart (hot-reload)
curl -X PUT http://localhost:8001/symbols -H "Content-Type: application/json" \
  -d '{"symbols": ["EURUSD","USDJPY","XAUUSD","GBPUSD"], "apply_mode": "replace"}'

# Afegir símbols (diff)
curl -X PUT http://localhost:8001/symbols -H "Content-Type: application/json" \
  -d '{"symbols": ["GOOGUSD"], "apply_mode": "diff"}'

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer

# Smoke canònic (up + checks /health /status /symbols /docs /ui + artifact)
./scripts/run_smoke.sh realtime_datalayer
# Artifact: datafiles/realtime_datalayer/runs/<ts>_smoke.json
```

## Canviar símbols des del web

1. Obrir http://localhost:8001/ui
2. Editar el textarea (JSON array de símbols)
3. Triar apply_mode: replace o diff
4. Clic "PUT /symbols"

## Llista d'assets (exemple)

EURUSD, USDJPY, XAUUSD (prefer perp), GBPUSD, GOOGUSD, NVDAUSD, DAXEUR, SPXUSD.
Config guardada a `{REALTIME_DATALAYER_ROOT}/config/symbols.json`; recarregada en reinici.

---

## Tests

```bash
./scripts/run_tests.sh realtime_datalayer   # ràpid, 0-network
./test.sh testing/run_all.py                # full suite (només milestones)
```
