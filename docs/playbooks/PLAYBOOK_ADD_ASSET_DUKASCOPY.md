# PLAYBOOK — Afegir cobertura històrica Dukascopy

**Objectiu:** Afegir dades històriques M1 per un asset via backfill Dukascopy (RAW bi5 → Parquet).

**Casos reals:** EURUSD, XAUUSD (T8.1, T9.07–T9.14)

---

## 1. Verificació asset

### Com saber si existeix

Dukascopy exposa dades M1 via URL binària:

```
https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH_0IDX}/{DAY}/BID_candles_min_1.bi5
```

**Prova manual (un dia conegut):**

```bash
# EURUSD 2024-01-15 (dilluns)
curl -sI "https://datafeed.dukascopy.com/datafeed/EURUSD/2024/00/15/BID_candles_min_1.bi5"
# Espera: HTTP 200, Content-Length > 0

# XAUUSD
curl -sI "https://datafeed.dukascopy.com/datafeed/XAUUSD/2024/00/15/BID_candles_min_1.bi5"

# Símbol nou (provar)
curl -sI "https://datafeed.dukascopy.com/datafeed/NEWSYMBOL/2024/00/15/BID_candles_min_1.bi5"
```

**Interpretació:**
- HTTP 200 + body no buit → asset disponible
- HTTP 404 o body buit → asset no disponible o no suportat

### Prova via CLI (opcional)

```bash
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm historical_datalayer \
  python3 -m application.data.dukascopy_bi5 \
    --symbol EURUSD --from 2024-01-15 --to 2024-01-16 --out /tmp/test.csv
# Si retorna candles → OK
```

---

## 2. Mapping

**Diferències amb Ostium:**
- Dukascopy usa símbols estàndard FX: EURUSD, XAUUSD, GBPUSD, USDJPY, etc.
- No hi ha mapping XXX→XXXUSD com a Ostium (equities).
- El símbol a la URL ha de coincidir amb el que Dukascopy llista (majoritàriament majors FX + metalls).

**Assets verificats:** EURUSD (2003-05→), XAUUSD (2003→), GBPUSD, USDJPY, AUDUSD.

---

## 3. Tipus de dades

| Tipus | Font | Format |
|-------|------|--------|
| **Ticks** | `{HOUR}h_ticks.bi5` | 20 bytes/tick, LZMA |
| **Candles M1** | `BID_candles_min_1.bi5` | 24 bytes/candle, LZMA |

**Pipeline actual (T9.13+):** RAW bi5 → Parquet ticks v1 → DuckDB query. `DUKASCOPY_PARQUET_ACTIVE=ticks`.

---

## 4. Backfill

### Opció A — sync_symbol.sh (recomanat)

```bash
# Sync complet (2003→avui)
./scripts/sync_symbol.sh EURUSD

# Sync rang concret
./scripts/sync_symbol.sh XAUUSD --from 2010-01-01 --to 2026-03-01

# Amb retries
./scripts/sync_symbol.sh EURUSD --max-retries 2 --chunk-years 5
```

**Flux intern:**
1. `POST /data/coverage/{symbol}/rebuild` — estat des del disc
2. `POST /data/sync` — job async (retorna job_id)
3. Poll `GET /data/sync/{job_id}` fins DONE/FAILED
4. Rebuild coverage post-sync
5. Auto-retry si gaps

### Opció B — POST /sync manual

```bash
# Bloc 1 (2003–2012)
curl -X POST http://localhost:8081/data/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","tf":"1m","from":"2003-01-01","to":"2012-12-31"}'

# Bloc 2 (2013–2022)
curl -X POST http://localhost:8081/data/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","tf":"1m","from":"2013-01-01","to":"2022-12-31"}'

# Bloc 3 (fins avui)
curl -X POST http://localhost:8081/data/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","tf":"1m"}'
```

**Notes:**
- Màxim 10 anys per crida (guardrail)
- Idempotent: 2a crida → `status=up_to_date`
- Poll `GET /data/sync/{job_id}` fins DONE

### Wrapper per símbols llargs (ex: sync_xauusd_full.sh)

Per rangs molt llargs (2003→avui), usar script dedicat o `sync_symbol.sh` en chunks.

---

## 5. Parquet

### Path físic

```
datafiles/historical_parquet_ticks_v1/{SYMBOL}/tf=1m/year=YYYY/month=MM/data.parquet
```

### Verificació

```bash
ls -la datafiles/historical_parquet_ticks_v1/EURUSD/tf=1m/year=2024/month=01/
# Espera: data.parquet
```

### Rebuild mes manual (si cal)

```bash
docker exec historical-datalayer python3 application/tools/build_dukascopy_parquet_ticks.py \
  --symbol EURUSD \
  --from 2024-01-01 \
  --to 2024-02-01 \
  --out-root /datafiles/historical_parquet_ticks_v1 \
  --raw-root /datafiles
```

---

## 6. Coverage

### API coverage

```bash
curl -s "http://localhost:8081/data/coverage/EURUSD?source=dukascopy" | python3 -m json.tool
```

**Camps rellevants:** `months_done`, `months_missing`, `coverage_from`, `coverage_to`, `total_rows`.

### Rebuild coverage (si index desincronitzat)

```bash
curl -X POST "http://localhost:8081/data/coverage/EURUSD/rebuild"
```

---

## 7. Limitacions

| Limitació | Descripció |
|-----------|-------------|
| **Assets no disponibles** | Dukascopy no té tots els símbols. Provar URL bi5 abans. |
| **Gaps coneguts** | EURUSD 2007-06→2011-12: 55 mesos buits (font pública). |
| **Diferències amb Ostium** | Ostium = live; Dukascopy = històric. Símbols poden divergir (ex: NDXUSD vs QQQ). |
| **Rate limits** | Evitar massa requests simultanis; sync_symbol.sh fa chunks. |

---

## 8. Escalat al PM

Atura't i escala si:
- L'asset no retorna HTTP 200 a la URL bi5
- Dubtes sobre disponibilitat del símbol a Dukascopy
- Necessites mapping Ostium↔Dukascopy (ex: QQQ vs NDXUSD)

---

## Definition of Done

- [ ] Asset verificat via URL bi5 (HTTP 200)
- [ ] sync_symbol.sh o POST /sync executat
- [ ] Parquet físic a `historical_parquet_ticks_v1/{SYMBOL}/`
- [ ] `GET /data/coverage/{SYMBOL}?source=dukascopy` retorna months_done > 0
- [ ] `GET /data/ohlcv/{SYMBOL}?source=dukascopy&tf=1m&limit=10` retorna candles
