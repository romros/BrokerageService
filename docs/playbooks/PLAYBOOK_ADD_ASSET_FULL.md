# PLAYBOOK — Afegir asset complet (live + històric)

**Objectiu:** Afegir un asset amb cobertura completa: Ostium live + Dukascopy històric.

**Casos reals:** EURUSD, XAUUSD (Ostium live + Dukascopy backfill)

---

## Fase 1 — Ostium (ingestió + persistència)

Seguir [PLAYBOOK_ADD_ASSET_OSTIUM.md](PLAYBOOK_ADD_ASSET_OSTIUM.md) completament:

1. Verificar suport Ostium (API latest-price)
2. Config: SYMBOLS, OSTIUM_SYMBOLS, mapping (si cal), MARKET_HOURS_UNKNOWN (si cal)
3. Ingestió: ticks i candles a realtime
4. CSV: path `candles/{SYMBOL}/`
5. Rollover real
6. Parquet Ostium: `historical_parquet_ostium_v1/{SYMBOL}/`
7. Integritat: gaps=0, duplicates=0
8. No regressió

**Checkpoint:** `curl /data/ohlcv/{SYMBOL}?source=ostium&tf=1m&limit=5` retorna dades.

---

## Fase 2 — Dukascopy (backfill històric)

Seguir [PLAYBOOK_ADD_ASSET_DUKASCOPY.md](PLAYBOOK_ADD_ASSET_DUKASCOPY.md):

1. Verificar asset a Dukascopy (URL bi5)
2. sync_symbol.sh o POST /sync
3. Parquet Dukascopy: `historical_parquet_ticks_v1/{SYMBOL}/`
4. Coverage verificat

**Checkpoint:** `curl /data/ohlcv/{SYMBOL}?source=dukascopy&tf=1m&limit=5` retorna dades.

**Nota:** Si l'asset no existeix a Dukascopy (ex: MSFT, NVDA, NDXUSD), aquesta fase no aplica. L'asset queda només Ostium.

---

## Fase 3 — Validació

### Coherència per source

```bash
# Ostium (recent)
curl -s "http://localhost:8081/data/ohlcv/EURUSD?source=ostium&tf=1m&limit=5"

# Dukascopy (històric)
curl -s "http://localhost:8081/data/ohlcv/EURUSD?source=dukascopy&tf=1m&limit=5"

# Coverage per source
curl -s "http://localhost:8081/data/coverage/EURUSD?source=ostium"
curl -s "http://localhost:8081/data/coverage/EURUSD?source=dukascopy"
```

### Integritat

Per cada source amb dades, validar amb `compute_ohlcv_integrity_report` (veure playbook Ostium §7).

---

## Fase 4 — Estat final

| Criteri | Ostium | Dukascopy |
|---------|--------|-----------|
| Ingestió/realtime | ✅ | N/A |
| CSV | ✅ | N/A |
| Parquet | ✅ | ✅ |
| `/data/ohlcv?source=` | ✅ | ✅ |
| Integritat | ✅ | ✅ |

**Asset ready** quan:
- source=ostium retorna dades recents
- source=dukascopy retorna dades històriques (si aplica)
- Cap regressió en altres símbols

---

## Casos especials

### Asset només Ostium (MSFT, NVDA, NDXUSD)

- Fase 1 completa
- Fase 2: SKIP (Dukascopy no té l'asset)
- Estat final: asset usable per live; històric limitat a Ostium

### Asset només Dukascopy (backfill sense live)

- Fase 1: SKIP
- Fase 2 completa
- Ús: backtest, no trading live

### Divergència de símbols (QQQ vs NDXUSD)

- Ostium: NDXUSD (QQQ no suportat)
- Dukascopy: podria tenir QQQ (futur)
- Documentar a ESTAT.md: `source=ostium` → NDXUSD, `source=dukascopy` → QQQ

---

## Definition of Done

- [ ] Fase 1 (Ostium) completa — si asset a Ostium
- [ ] Fase 2 (Dukascopy) completa — si asset a Dukascopy
- [ ] Fase 3: coherència i integritat verificades
- [ ] Fase 4: asset ready
- [ ] Documentació a ESTAT.md
