# Safety Runbook — BrokerageService

**Objectiu:** Procediments operatius mínims per detectar incidents i actuar. No depèn de memòria.

**Docs:** [ESTAT.md](ESTAT.md) · [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md) · [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

---

## 1) TZ i coherència

**Config:**
- `CANONICAL_TZ=America/New_York` (config, partició, queries)
- `TZ=America/New_York` (container runtime, logs, display)

**Verificar dins Docker:**
```bash
docker compose run --rm brokerage date
docker compose run --rm brokerage python3 -c "import time,datetime; print(datetime.datetime.now()); print(time.tzname)"
```
Hora NY i `('EST','EDT')` quan toca → OK.

---

## 2) Kill switch LIVE

**Variable:** `ENABLE_LIVE_TRADING=0` | `1`

- **0 (default):** Bloqueja `open_position` en mode LIVE. Només paper/read.
- **1:** Permet execució real en LIVE.

**On:** `.env` o `docker-compose.yml` environment.

---

## 3) Guards de risc

| Variable | Què fa | Valor recomanat |
|----------|--------|-----------------|
| `MAX_OPEN_POSITIONS` | Màxim posicions obertes simultànies | 1 (conservador) |
| `MAX_NOTIONAL_USDC` | Màxim notional per posició (0 = desactivat) | 0 o 500–1000 per testnet |

**On:** `application/config/live_guards_config.py`; llegit de `os.getenv`.

---

## 4) Reconcile

**Què vol dir "diff":** ReconcileService compara posicions del venue amb el tracking local. Si hi ha divergència → `ReconcileResult` (missing_locally, extra_locally, mismatch).

**On mirar logs:** stdout/stderr del procés; `datafiles/smoke_runs/` si smoke amb `--repeat`.

**Auto-repair v1:** `build_actions` → `IReconcileSink.handle` → `MarkStalePosition` + `RequestResync`. No fa trades; marca stale i demana resync.

---

## 5) Incidents típics i resposta

### Posicions obertes després d'e2e/smoke

**Símptoma:** `positions_after > 0` al final d'un run.

**Acció:**
```bash
docker compose run --rm brokerage python3 -m application.e2e_trade \
  --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20 \
  --settle-timeout-s 120 --poll-s 2
```
`force_close_remaining` ja implementat: si timeout, tanca posicions restants i retry.

**Validar:** Output `positions_after=0`; o consultar `GET /api/v1/broker/positions?venue=lighter`. Per verificar PnL vs web: comparar `closed_pnl` del log amb Trade History (testnet.app.lighter.xyz).

### "Account not found"

**Símptoma:** Warnings "Account not found" als logs.

**Comprovar:** `LIGHTER_BASE_URL`, `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX` coherents. ApiClient amb `Configuration(host=base_url)`.

---

## 6) Comandes (copiable)

```bash
# Suite general (mock + API smoke)
./test.sh testing/run_all.py

# Smoke mock (ràpid)
docker compose run --rm brokerage python3 -m application.smoke --venue mock --mode PAPER --seconds 5

# Smoke lighter (paper testnet)
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 120

# Smoke 3× (evidència Gate C)
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 120 --repeat 3 --pause-s 5

# Soak 10 min (default) o 15 min
./scripts/soak_smoke.sh
./scripts/soak_smoke.sh 900

# WS Preflight (P2.0): valida candle stream (≥2 candles, ts monotònic, delta 60s)
# Requereix: broker corrent (docker compose up) amb VENUE=lighter MODE=paper
# Des de host (broker a localhost:8000):
python3 -m application.tools.ws_preflight --ws-url ws://localhost:8000/api/v1/ws --symbol ETH --minutes 3
# Des de container (broker = service brokerage):
docker compose run --rm brokerage python3 -m application.tools.ws_preflight \
  --ws-url ws://brokerage:8000/api/v1/ws --symbol ETH --minutes 3

# WS Soak (P2.1): 15 min, valida estabilitat pipeline candles via WS
# Broker amb pipeline (fake feed): docker compose -f docker-compose.yml -f docker-compose.soak.yml up -d
# Recorda: docker compose build brokerage si has canviat codi
./scripts/soak_ws.sh        # 15 min (default)
./scripts/soak_ws.sh 900    # 15 min
./scripts/soak_ws_quick.sh  # test ràpid 60s
# OK si: WS_SOAK_RESULT status=OK, candles>=1, reconnects<=3, max_gap_s<=120

# WS Soak MAINNET (P2.2): Lighter real feed, 15 min
# Requereix: .env amb LIGHTER_L1_ADDRESS, LIGHTER_L1_PRIVATE_KEY, LIGHTER_API_PRIVATE_KEY
./scripts/soak_ws_mainnet.sh        # 15 min
./scripts/soak_ws_mainnet.sh 900    # 15 min
# Log: datafiles/ws_soak/<ts>_ws_soak_15m_mainnet.log

# Manual amb log-path explícit:
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 600 --log-path /datafiles/smoke_runs/soak_$(date +%Y%m%d_%H%M%S).log

# Freqtrade runner 15 min (PAPER testnet, position_pnl cada 30s, closed_pnl al final)
VENUE=lighter docker compose up -d brokerage
docker compose run --rm brokerage python3 -m application.tools.freqtrade_runner --venue lighter --mode PAPER --symbol ETH --minutes 15
# Log: datafiles/freqtrade_runs/<ts>_ETH_15m.log. Verificar PnL vs Trade History web.

# E2E 1 run
docker compose run --rm brokerage python3 -m application.e2e_trade \
  --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20 \
  --settle-timeout-s 120 --poll-s 2

# E2E 3× (evidència DONE — executar 3 cops consecutius)
docker compose run --rm brokerage python3 -m application.e2e_trade \
  --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20 \
  --settle-timeout-s 120 --poll-s 2
```

---

## 7) Criteri DONE (sanity)

- `./test.sh testing/run_all.py` → OK
- Smoke 3× (lighter, 120s) → ok=3 failed=0
- E2E 3× → positions_after=0
- Soak 10 min → log guardat, sense errors crítics ✅ (evidència: soak_20260213_212644.log)
- WS Soak 15 min → `./scripts/soak_ws.sh 900` → WS_SOAK_RESULT status=OK ✅ (evidència: 20260214_011714_ws_soak_15m.log, 15 candles)

**Referència:** [docs/ESTAT.md](ESTAT.md)
