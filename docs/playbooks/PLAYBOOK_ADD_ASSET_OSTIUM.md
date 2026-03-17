# PLAYBOOK — Afegir asset Ostium (live + persistència durable)

**Objectiu:** Afegir un asset live amb ingestió realtime, persistència CSV, rollover Parquet i consulta històrica.

**Casos reals:** MSFT, NVDA, NDXUSD (TASCA 3/4/5)

---

## Quick Start (check ràpid)

Abans de començar, respon:

1. L'asset existeix a Ostium? (`curl .../latest-price?asset=SYMBOL` → 200?)
2. Quin és el mapping correcte? (ex: MSFT → MSFTUSD)
3. Cal un proxy? (ex: QQQ → NDXUSD)
4. Objectiu: live + persistència durable

Si no pots respondre en <2 minuts → escala al PM abans de continuar.

---

## Decisions importants

- Els assets depenen del venue (no tots existeixen a Ostium)
- El mapping pot diferir del ticker (ex: MSFT → MSFTUSD)
- Alguns assets requereixen proxy: QQQ (ETF) → NDXUSD (índex)
- Ostium = live + retenció pròpia (CSV → Parquet)

---

## 1. Verificació suport Ostium

**Regla:** Els assets es defineixen per availability del venue, no per desig del producte.

### Com provar asset via API

```bash
# Provar variant directa (ex: MSFT, QQQ, NDXUSD)
curl -s "https://metadata-backend.ostium.io/PricePublish/latest-price?asset=MSFT"
curl -s "https://metadata-backend.ostium.io/PricePublish/latest-price?asset=QQQ"
curl -s "https://metadata-backend.ostium.io/PricePublish/latest-price?asset=NDXUSD"

# Provar variant XXXUSD (equities/indices)
curl -s "https://metadata-backend.ostium.io/PricePublish/latest-price?asset=MSFTUSD"
curl -s "https://metadata-backend.ostium.io/PricePublish/latest-price?asset=QQQUSD"
```

**Interpretació:**
- HTTP 200 + JSON `{"mid": ..., "bid": ..., "ask": ...}` → asset suportat
- HTTP 400 "Invalid asset" → asset NO suportat

### Com detectar mapping correcte

| Símbol desitjat | Prova 1 | Prova 2 | Resultat |
|-----------------|---------|---------|----------|
| MSFT | `asset=MSFT` → 400 | `asset=MSFTUSD` → 200 | Mapping MSFT→MSFTUSD |
| NVDA | `asset=NVDA` → 400 | `asset=NVDAUSD` → 200 | Mapping NVDA→NVDAUSD |
| NDXUSD | `asset=NDXUSD` → 200 | — | Sense mapping |
| QQQ | `asset=QQQ` → 400 | `asset=QQQUSD` → 400 | No suportat → buscar proxy (NDXUSD) |

**Si cap variant funciona:** Escalar al PM. No crear mapping artificial.

---

## 2. Configuració

### Fitxers a modificar

| Fitxer | Què afegir |
|--------|-------------|
| `deploy/compose/docker-compose.split.yml` | SYMBOLS, OSTIUM_SYMBOLS |
| `apps/realtime_datalayer/symbol_config.py` | OSTIUM_DEFAULT_MAPPING (si cal) |
| `application/market_hours/fx_24_5.py` | MARKET_HOURS_UNKNOWN_SYMBOLS (equity/índex) |

### Pas 2.1 — docker-compose.split.yml

```yaml
# realtime_datalayer environment:
- SYMBOLS=${SYMBOLS:-XAUUSD,EURUSD,MSFT,NVDA,NDXUSD,NEWSYMBOL}
- OSTIUM_SYMBOLS=${OSTIUM_SYMBOLS:-EURUSD,GBPUSD,MSFT,NVDA,NDXUSD,NEWSYMBOL}
```

### Pas 2.2 — symbol_config.py (només si cal mapping)

```python
# OSTIUM_DEFAULT_MAPPING — logical_symbol → ostium_asset
OSTIUM_DEFAULT_MAPPING = {
    # ...
    "MSFT": "MSFTUSD",   # Ostium usa MSFTUSD
    "NVDA": "NVDAUSD",   # Ostium usa NVDAUSD
    # NDXUSD sense mapping (Ostium usa NDXUSD directament)
}
```

### Pas 2.3 — fx_24_5.py (equity/índex)

```python
# Indices/equities: calendari no fiable → market_hours=unknown
MARKET_HOURS_UNKNOWN_SYMBOLS = frozenset({
    "GOOGUSD", "NVDAUSD", "DAXEUR", "SPXUSD", "NDXUSD", "MSFT", "NVDA", "NEWSYMBOL"
})
```

**Quan afegir:** Equity US (MSFT, NVDA), índex (NDXUSD, SPXUSD). FX 24/5 (EURUSD, XAUUSD) no van aquí.

---

## 3. Ingestió

### Opció A — Rebuild realtime_datalayer (canvis de codi)

```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml \
  build realtime_datalayer
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml \
  up -d realtime_datalayer
```

**⚠️ PRODUCCIÓ:** No aturar realtime_datalayer sense planificar — es perden ticks nous.

### Opció B — Hot-reload (només nous símbols, sense canvis codi)

```bash
curl -X PUT http://localhost:8081/realtime/symbols \
  -H "Content-Type: application/json" \
  -d '{"symbols":["NEWSYMBOL"],"apply_mode":"diff"}'
```

### Validació ticks i candles

```bash
# Realtime OHLCV
curl -s "http://localhost:8081/realtime/api/v1/broker/ohlcv/NEWSYMBOL?tf=1m&limit=5" | python3 -m json.tool

# data_status per símbol
curl -s "http://localhost:8081/realtime/api/v1/broker/data_status" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('symbols',{}).get('NEWSYMBOL',{}))"
```

**Espera:** candles amb format `[[ts,o,h,l,c,v], ...]`, `candles_written` > 0 després d'uns minuts.

---

## 4. Persistència CSV

### Path esperat

```
datafiles/realtime_datalayer/candles/NEWSYMBOL/
```

### Verificació

```bash
ls -la datafiles/realtime_datalayer/candles/NEWSYMBOL/
# Espera: fitxers CSV per dia (ex: 2026-03-17.csv)
```

**Si no hi ha fitxers:** Comprovar que el símbol està a OSTIUM_SYMBOLS i no a OSTIUM_QUARANTINE_SYMBOLS. Mercat obert (o MARKET_HOURS_UNKNOWN_SYMBOLS).

---

## 5. Rollover

### Diferència dry-run vs real

| Mode | Comanda | Què fa |
|------|---------|--------|
| Dry-run | `--dry-run` | Mostra què s'escriuria, no escriu |
| Real | sense flag | Llegeix CSV, escriu Parquet, merge idempotent |

### Execució correcta

```bash
# Dry-run primer
./scripts/run_ostium_rollover.sh --symbol NEWSYMBOL --from 2026-03-17 --to 2026-03-18 --dry-run

# Rollover real (dates amb dades CSV)
./scripts/run_ostium_rollover.sh --symbol NEWSYMBOL --from 2026-03-17 --to 2026-03-18
```

**Output esperat:** `ostium_rollover DONE`, sense errors.

---

## 6. Historical

### Path Parquet

```
datafiles/historical_parquet_ostium_v1/NEWSYMBOL/tf=1m/year=YYYY/month=MM/data.parquet
```

### Consulta API

```bash
curl -s "http://localhost:8081/data/ohlcv/NEWSYMBOL?source=ostium&tf=1m&limit=20" | python3 -m json.tool
```

**Espera:** candles de Parquet + CSV merge (CSV guanya en overlap).

### Coverage

```bash
curl -s "http://localhost:8081/data/coverage/NEWSYMBOL?source=ostium" | python3 -m json.tool
```

---

## 7. Integritat

### Mòdul

`application/data/ohlcv_integrity.py` — `compute_ohlcv_integrity_report(candles)`

### Com validar

```bash
# Obtenir candles i validar (script ad-hoc)
curl -s "http://localhost:8081/data/ohlcv/NEWSYMBOL?source=ostium&tf=1m&limit=1000" | \
  python3 -c "
import sys, json
from application.data.ohlcv_integrity import compute_ohlcv_integrity_report
d = json.load(sys.stdin)
candles = d.get('candles', [])
r = compute_ohlcv_integrity_report(candles)
print(r)
assert r['valid'], r
"
```

**Criteris OK:** `duplicates=0`, `ts_step_errors=0`, `order_ok=True`, `ohlc_ok=True`, `valid=True`.

---

## 8. No regressió

Verificar que assets existents continuen funcionant:

```bash
curl -s "http://localhost:8081/realtime/api/v1/broker/ohlcv/EURUSD?tf=1m&limit=3"
curl -s "http://localhost:8081/realtime/api/v1/broker/ohlcv/MSFT?tf=1m&limit=3"
curl -s "http://localhost:8081/data/ohlcv/EURUSD?source=ostium&tf=1m&limit=3"
```

---

## 9. Errors comuns

| Error | Causa | Acció |
|-------|-------|-------|
| asset 400 Invalid asset | Símbol no suportat per Ostium | Provar variants XXXUSD; si cap → buscar proxy o escalar PM |
| CSV no generat | Símbol no a OSTIUM_SYMBOLS, o quarantine, o market closed | Afegir a allowlist; equity/índex → MARKET_HOURS_UNKNOWN_SYMBOLS |
| Mapping incorrecte | Ostium usa nom diferent (ex: MSFTUSD) | Afegir a OSTIUM_DEFAULT_MAPPING |
| Rollover 0 candles | Rang sense dades CSV o dates incorrectes | Verificar path CSV; usar --from/--to amb dies que tinguin dades |
| duplicates > 0 | Writer contaminat | Hard stop; no declarar primary; investigar |

---

## 10. Escalat al PM

Atura't i escala si:
- L'asset desitjat no existeix a Ostium i no hi ha proxy clar
- Dubtes sobre equivalència funcional (ex: QQQ vs NDXUSD)
- Contradiccions amb arquitectura
- Qualsevol desviació del patró MSFT/NVDA/NDXUSD

---

## Definition of Done

Un asset Ostium està correctament integrat si:

- [ ] És visible a `/realtime` (ohlcv, data_status)
- [ ] Escriu dades a CSV (`candles/{SYMBOL}/`)
- [ ] Passa rollover real
- [ ] Existeix Parquet físic (`historical_parquet_ostium_v1/{SYMBOL}/`)
- [ ] Es pot consultar via `/data?source=ostium`
- [ ] Passa validació d'integritat (gaps=0, duplicates=0)
- [ ] No hi ha regressions en altres assets (EURUSD, MSFT, NVDA)

Si algun punt no es compleix → la tasca NO està acabada.
