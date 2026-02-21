# Realtime DataLayer v1 — Estat

**Data:** 2026-02-21

---

## Responsabilitat

**Fa:** ingest de preus en temps real via Ostium (polling REST), emmagatzematge de candles 1m, exposició OHLCV+headers `X-Data-*`, heartbeat quan el mercat és tancat, hot-reload de símbols, market-hours awareness per 8 instruments.

**No fa:** backfill Dukascopy (→ historical_datalayer), execució d'ordres (→ trading_service), backtesting (→ trading_service).

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | ✅ | `docker compose -f ... up -d realtime_datalayer` |
| GET /health | ✅ | `{"status":"ok"}` |
| GET /status | ✅ | stats, retention, uptime, timezone fields |
| GET/PUT /symbols | ✅ | Hot-reload símbols sense restart |
| Instrument resolution | ✅ | spot/perp, override a config |
| Ostium ingest 24/7 | ✅ | OstiumCandleIngestService |
| Sense Dukascopy | ✅ | NullBackfillProvider; independent (AGENTS_ARQUITECTURA) |
| Market-hours aware | ✅ | market_closed no degrada; heartbeat mode (Phase 3); **fix cap de setmana 2026-02-21** |
| **Phase 3: Heartbeat mode** | ✅ | market_closed → poll reduït (OSTIUM_CLOSED_HEARTBEAT_S, default 60s) |
| **Phase 4: X-Data-* headers** | ✅ | GET /ohlcv/{symbol} emet Source/Coverage-From/To/Missing-Minutes/Max-Gap-S |
| Tick recorder | ✅ | OstiumTickRecorder (opt-in) |
| Storage candles | ✅ | datafiles/realtime_datalayer/candles/ |
| Storage ticks | ✅ | lab/out/ostium_forensics o REALTIME_DATALAYER_ROOT/ticks |
| Retenció candles | ✅ | REALTIME_CANDLES_MAX_HOURS (default 4320h = 180 dies) |
| Tests curts | ✅ | `./scripts/run_tests.sh realtime_datalayer` |

---

## Fitxers i directoris canònics

```
apps/realtime_datalayer/
  app.py                      # Entrypoint (SERVICE_ROLE=realtime_datalayer)
  market_hours/
    engine.py                 # get_market_state_ny() — perfils XAU/indices/RTH/FX
    __init__.py               # re-exporta get_market_state_ny
  symbol_config.py            # Càrrega/persistència symbols.json
  ostium_ingest.py            # OstiumCandleIngestService
  tick_recorder.py            # OstiumTickRecorder (opt-in)

testing/realtime_datalayer/   # Tests integrats (0-network)
testing/unit/                 # Tests unitaris (market_hours, golden, etc.)
testing/suites/realtime_datalayer.txt  # Suite canònica

datafiles/realtime_datalayer/
  candles/                    # JSONL per símbol
  ticks/                      # Forensics opt-in
  config/symbols.json         # Símbols actius (persistit)
```

---

## Horaris de mercat (engine.py)

| Símbol | Perfil | Obert | Tancat |
|--------|--------|-------|--------|
| XAUUSD | ostium_xau_break | Dg 18:00→Div 17:00 NY (break diari 17:00–18:00) | Dissabte + Dg <18:00 |
| DAXEUR, SPXUSD | ostium_indices_break | Dg 18:00→Div 17:00 NY (break diari 17:00–18:00) | Dissabte + Dg <18:00 |
| NVDAUSD | ostium_rth_equities | Dies laborables 09:31–15:59 NY | Cap de setmana + fora RTH |
| GOOGUSD | us_equities_ny | Dies laborables 09:30–16:00 NY | Cap de setmana + fora RTH |
| EURUSD, GBPUSD, USDJPY, AUDUSD | fx_24_5 | Dg 17:00 UTC→Div 22:00 UTC | Dissabte + Dg <17:00 UTC |

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

# OHLCV amb headers X-Data-*
curl -sI "http://localhost:8081/ohlcv/EURUSD?tf=1m&limit=10" | grep X-Data

# Canviar símbols sense restart (hot-reload)
curl -X PUT http://localhost:8081/symbols -H "Content-Type: application/json" \
  -d '{"symbols": ["EURUSD","USDJPY","XAUUSD","GBPUSD"], "apply_mode": "replace"}'

# Afegir símbols (diff)
curl -X PUT http://localhost:8081/symbols -H "Content-Type: application/json" \
  -d '{"symbols": ["GOOGUSD"], "apply_mode": "diff"}'

# Rebuild (si has canviat codi — el codi es baka a la imatge, no hi ha volume mount)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer

# Smoke canònic
./scripts/run_smoke.sh realtime_datalayer
```

### Canviar símbols des del web

1. Obrir http://localhost:8081/ui
2. Editar el textarea (JSON array de símbols)
3. Triar apply_mode: replace o diff
4. Clic "PUT /symbols"

---

## Tests

```bash
# Ràpid (0-network) — usa per validar canvis locals
./scripts/run_tests.sh realtime_datalayer

# Full suite
./test.sh testing/run_all.py
```

**Suite inclou:** market_hours (XAU, índexs, NVDA, GOOGUSD, FX), golden anti-regressió cap de setmana, warmup gating, health states, candle builder, retention, docs OpenAPI, symbols API, supervisor hot-reload, instrument resolution, pause/resume, heartbeat, OHLCV headers.

---

## Què NO entra aquí

- **Backfill Dukascopy** → `apps/historical_datalayer/`
- **Execució d'ordres / SL/TP** → `apps/trading_service/`
- **Backtesting** → `apps/trading_service/` (BacktestMarketDataProvider)
- **Compat Ostium↔Dukascopy** → scripts `run_compat.sh` (opt-in LAB)

---

## Per què pots veure closed / warning i és OK

- **market_state=closed / state=paused_closed:** Mercat tancat (break diari XAU/DAX/SPX, RTH tancat NVDA, cap de setmana). No és incident. **Phase 3:** heartbeat poll cada `OSTIUM_CLOSED_HEARTBEAT_S` (default 60s).
- **market_state=unknown:** Símbol sense perfil d'horaris conegut.
- **DEGRADED** només per errors reals durant market_open. Degraded és **non-blocking**: continua polling amb backoff; autorecover quan arriba tick nou.

## Override horaris (symbols.json)

```json
{
  "symbols": ["EURUSD", "XAUUSD", "NVDAUSD"],
  "market_hours_overrides": {"NVDAUSD": "ostium_rth_equities"}
}
```
