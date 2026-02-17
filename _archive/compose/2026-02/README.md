# Arxiu compose overrides (2026-02)

**Per què:** Pivot Ostium. Lighter mainnet EURUSD/WS soak ja no és camí principal.

**Reemplaçament canònic:**
- Data Layer prod: `deploy/compose/overrides/data-layer.yml` + `./scripts/run_smoke.sh data-layer`
- WS soak (fake): `deploy/compose/overrides/soak.yml` + `./scripts/run_soak.sh 15 ws`

**Contingut arxivat:**
- `mainnet.yml` — Lighter mainnet real feed (ETH,BTC)
- `mainnet-eurusd.yml` — Lighter forex/metals (EURUSD,XAU)

Eren usats per `soak_ws_mainnet.sh` (Lighter-specific).
