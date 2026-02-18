# Compose overrides

Tots els docker-compose overrides operatius. Convenció: un fitxer per perfil.

| Fitxer | Perfil | Descripció |
|--------|--------|-------------|
| data-layer.yml | data-layer | Data Layer prod v0 (prefetch + writer + gates) |
| soak.yml | ws | WS soak (fake feed, ETH/BTC) |
| ostium.yml | ostium | Ostium Data Layer prod v0 (realtime Ostium + backfill Dukascopy). DATA_LAYER_WRITE_MODE=realtime_plus_backfill. Opt-in experimental. |

**Gotcha permisos (resolt):** data-layer i ostium usen `user: ${UID}:${GID}` perquè `datafiles/compat_reports/` sigui writable des del host (run_compat.sh, run_soak post-compat). Els scripts run_smoke.sh i run_soak.sh exporten UID/GID automàticament. Si arranques compose manualment, fes `export UID=$(id -u) GID=$(id -g)` abans.

**Ús:**
```bash
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage
docker compose -f docker-compose.yml -f deploy/compose/overrides/soak.yml config  # validar
docker compose -f docker-compose.yml -f deploy/compose/overrides/ostium.yml config  # Ostium opt-in
```
