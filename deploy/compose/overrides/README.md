# Compose overrides

Tots els docker-compose overrides operatius. Convenció: un fitxer per perfil.

| Fitxer | Perfil | Descripció |
|--------|--------|-------------|
| data-layer.yml | data-layer | Data Layer prod v0 (prefetch + writer + gates) |
| soak.yml | ws | WS soak (fake feed, ETH/BTC) |
| ostium.yml | ostium | Ostium Data Layer prod v0 (realtime Ostium + backfill Dukascopy) |

**Ús:**
```bash
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage
docker compose -f docker-compose.yml -f deploy/compose/overrides/soak.yml config  # validar
```
