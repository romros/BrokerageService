# historical_datalayer — Estat

**Data:** 2026-02-19

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | 🟡 | Entrypoint creat; pendent validació completa |
| GET /health | 🟡 | Pendent |
| Backfill Dukascopy | ✅ | Phase 15: `run_historical_backfill.py` + Parquet storage particionat |
| Parquet storage | ✅ | Phase 15: `infrastructure/storage/parquet_store.py`; particionat mensual; idempotent |
| Compat engine | 🟡 | Existent al LAB; pendent integrar al servei |
| Compat registry | 🟡 | `compat_reports/ostium_compat_registry.json` via run_compat.sh |
| Stitching gated | 🟡 | Lògica existent; pendent activació per servei |
| Tests curts | 🟡 | `./scripts/run_tests.sh historical_datalayer` |

---

## DoD del servei

- [x] Backfill Dukascopy funcional (Phase 15: Parquet particionat)
- [ ] Compat report genera registry correcte
- [ ] Stitching gated per compat PASS; mixed coherent
- [ ] `/health` i `/data_status` operatius
- [ ] Tests de role wiring passen

---

## Comandes canòniques

```bash
# Arrencar servei
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d historical_datalayer

# Verificar
curl -s http://localhost:8082/health
curl -s http://localhost:8082/data_status

# Compat report (via scripts)
./scripts/run_compat.sh ostium EURUSD

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build historical_datalayer

# Tests
./scripts/run_tests.sh historical_datalayer
```

---

## Notes

- **Dukascopy:** Via `dukascopy-python`. Suporta EURUSD, XAUUSD (i altres FX majors). GBPJPY i equities limitats.
- **Compat LAB → prod:** Els scripts `lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py` han validat EURUSD (PASS) i XAUUSD (FAIL corr 0.43). Pendent integrar lògica al servei.
- **realtime_datalayer independent:** Per disseny, historical_datalayer NO té dependència obligatòria de realtime_datalayer; el stitching és opcional.
