# Realtime DataLayer v1 — Estat

**Data:** 2026-02-19

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
| Sense Dukascopy | ✅ | NullBackfillProvider; independent (AGENTS_ARQUITECTURA) |
| Market-hours aware | ✅ | market_closed no degrada; ingest pausat per símbol quan closed |
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
curl -s http://localhost:8081/health
curl -s http://localhost:8081/status
curl -s http://localhost:8081/symbols
curl -s http://localhost:8081/api/v1/broker/data_status

# UI i docs (túnel: ssh -L 8081:localhost:8081 user@host)
# Obrir al navegador: http://localhost:8081/  o  http://localhost:8081/ui  i  http://localhost:8081/docs
# Dashboard: auto-refresh 5s/10s/30s, cards per símbol, PUT /symbols diff/replace

# Canviar símbols sense restart (hot-reload)
curl -X PUT http://localhost:8081/symbols -H "Content-Type: application/json" \
  -d '{"symbols": ["EURUSD","USDJPY","XAUUSD","GBPUSD"], "apply_mode": "replace"}'

# Afegir símbols (diff)
curl -X PUT http://localhost:8081/symbols -H "Content-Type: application/json" \
  -d '{"symbols": ["GOOGUSD"], "apply_mode": "diff"}'

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer

# Smoke canònic (up + checks /health /status /symbols /docs /ui + artifact)
./scripts/run_smoke.sh realtime_datalayer
# Artifact: datafiles/realtime_datalayer/runs/<ts>_smoke.json
```

## Canviar símbols des del web

1. Obrir http://localhost:8081/ui
2. Editar el textarea (JSON array de símbols)
3. Triar apply_mode: replace o diff
4. Clic "PUT /symbols"

## Per què pots veure closed / warning i és OK

- **market_state=closed / state=paused_closed:** Mercat tancat (break diari XAU/DAX/SPX, RTH tancat NVDA, cap de setmana FX). No és incident. Ingest pausat; es repren quan obre.
- **market_state=unknown:** Símbol sense perfil d'horaris conegut (ara tots els símbols per defecte tenen perfil). `state=warning` si no hi ha dades.
- **GOOGUSD → us_equities_ny:** RTH 09:30–16:00 NY. Fora d'horari: `paused_closed` + `next_open_local`. (Abans era `unknown`.)
- **WARMUP:** Durant arrencada (`symbol_uptime_s < warmup_minutes`), `missing_minutes_24h` no pot degradar. `coverage_*` es mostren com a mètrica informativa però no governen `state`.
- **coverage_* (informatives):** `coverage_expected_minutes`, `coverage_missing_minutes`, `coverage_ratio` disponibles a `/symbols` i `/status`. Basades en `symbol_uptime_s`, no en 24h fix.
- **DEGRADED** només per errors reals durant market_open. Degraded és **non-blocking**: continua polling amb backoff (base 2s, max 60s); autorecover quan arriba tick nou; pause només per `paused_closed`. `/symbols` inclou `next_poll_in_s`, `degrade_reason`.

## Override horaris (symbols.json)

```json
{
  "symbols": ["EURUSD", "XAUUSD", "NVDAUSD"],
  "market_hours_overrides": {"NVDAUSD": "ostium_rth_equities"}
}
```

## Llista d'assets (exemple)

EURUSD, USDJPY, XAUUSD (prefer perp), GBPUSD, GOOGUSD, NVDAUSD, DAXEUR, SPXUSD.
Config guardada a `{REALTIME_DATALAYER_ROOT}/config/symbols.json`; recarregada en reinici.

**Per què alguns tenen poques candles:** NVDA té horari curt (09:31–15:59 NY). Si el servei corre fora d'aquest horari, no rep ticks i no escriu candles. XAU/DAX/SPX tenen break diari 16:59–18:00 NY. Tots els actius es guarden; el nombre de candles depèn del temps que el mercat ha estat obert des de l'arrencada.

---

## Tests

```bash
./scripts/run_tests.sh realtime_datalayer   # ràpid, 0-network
./test.sh testing/run_all.py                # full suite (només milestones)
```
