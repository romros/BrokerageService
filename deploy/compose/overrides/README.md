# Compose overrides

Tots els docker-compose overrides operatius. Convenció: un fitxer per perfil.

**⚠️ Regla d’or:** Mai aturar ni recrear `realtime_datalayer` — és el gold, guarda les dades Ostium. `live_on`/`live_off` només toquen `trading_service`. Veure [SAFETY_RUNBOOK.md](../../docs/SAFETY_RUNBOOK.md) §0.

**Scaffold split vNext:** `deploy/compose/docker-compose.split.yml` — 3 serveis (realtime_datalayer, historical_datalayer, trading_service). Reutilitza mateixa imatge; és scaffold operatiu, encara no migració de codi. Veure `docs/ESTAT.md` § Arquitectura split vNext.

| Fitxer | Perfil | Descripció |
|--------|--------|-------------|
| data-layer.yml | data-layer | Data Layer prod v0 (prefetch + writer + gates) |
| soak.yml | ws | WS soak (fake feed, ETH/BTC) |
| ostium.yml | ostium | Ostium Data Layer prod v0 (realtime Ostium + backfill Dukascopy). DATA_LAYER_WRITE_MODE=realtime_plus_backfill. Opt-in experimental. |
| ostium-live-trading.yml | ostium-live | trading_service en mode LIVE Ostium (execució real testnet). **NO toca realtime_datalayer.** Requereix `lab/ostium/.env` amb RPC_URL, PRIVATE_KEY. Veure § Ostium LIVE smoke. |
| live.off.yml | paper (kill-switch) | trading_service en mode PAPER (ENABLE_LIVE_TRADING=0). Rollback segur. Usat per `./scripts/live_off.sh`. |

**Gotcha permisos (resolt):** data-layer i ostium usen `user: ${DOCKER_UID}:${DOCKER_GID}` perquè `datafiles/compat_reports/` sigui writable des del host (run_compat.sh, run_soak post-compat). Els scripts exporten DOCKER_UID/DOCKER_GID i comproven que datafiles/logs siguin writable. **Si el broker falla (Permission denied):** executa `sudo chown -R $(id -u):$(id -g) datafiles logs` una vegada.

**Ús:**
```bash
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage
docker compose -f docker-compose.yml -f deploy/compose/overrides/soak.yml config  # validar
docker compose -f docker-compose.yml -f deploy/compose/overrides/ostium.yml config  # Ostium opt-in
```

**Ostium LIVE:** Veure [docs/ESTAT.md](../../docs/ESTAT.md) § Ostium LIVE.

- **Run:** `./scripts/up_ostium_live.sh`
- **Smoke only:** `./scripts/run_ostium_live_smoke.sh --recreate --clean`

**Toggle LIVE/PAPER (T7.3.1):**
- `./scripts/live_on.sh` → LIVE (ostium-live-trading.yml + force-recreate trading_service)
- `./scripts/live_off.sh` → PAPER/kill-switch (live.off.yml + force-recreate trading_service)
- Verificació via `GET /trade/api/v1/broker/preflight`
