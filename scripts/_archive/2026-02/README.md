# Arxiu scripts (2026-02)

**Per què:** Ops Hygiene v1. Consolidar a run_smoke.sh i run_soak.sh amb profiles.

**Reemplaçament canònic:**
- Data Layer smoke: `./scripts/run_smoke.sh data-layer`
- Data Layer soak: `./scripts/run_soak.sh 30 data-layer`
- WS soak: `./scripts/run_soak.sh 15 ws`
- Smoke reconcile: `./scripts/run_smoke.sh smoke`

**Contingut arxivat:**
- run_data_layer_smoke.sh, run_data_layer_soak.sh → run_smoke/run_soak data-layer
- soak_ws.sh, soak_ws_mainnet.sh, soak_ws_quick.sh → run_soak ws
- soak_smoke.sh → run_smoke smoke
- run_data_layer_smoke.py, run_data_layer_soak.py → application/tools/data_layer_smoke.py, data_layer_soak.py
