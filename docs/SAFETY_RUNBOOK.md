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

- **0 (default):** Usa PaperVenueAdapter (zero tx). Market data mainnet, execució simulada.
- **1:** Permet execució real en LIVE (LighterVenueAdapter).

**On:** `.env` o `docker-compose.yml` environment.

**venue=paper:** Quan `MODE=paper` o `ENABLE_LIVE_TRADING=0`, el broker exposa `venue=paper`. Zero transaccions; no requereix credencials Lighter per execució (però sí per preus reals si `USE_FAKE_PRICE_FEED=0`).

---

## 2b) Fake vs real price feed

**Variable:** `USE_FAKE_PRICE_FEED=0` | `1`

- **1 (default a run_freqtrade_paper.sh):** Preus fake (ETH base 3500, drift). Sense xarxa. Per tests ràpids i CI.
- **0:** Preus reals de Lighter API (order book). Cal `.env` amb `LIGHTER_L1_ADDRESS`, `LIGHTER_L1_PRIVATE_KEY`, `LIGHTER_API_PRIVATE_KEY`.

**Com saber què s'usa:** `GET /api/v1/broker/mode` retorna `market_data_source`: `fake` | `real` | `n/a`. El freqtrade_runner ho mostra a l'inici.

**Paper amb preus reals (15 min):**
```bash
MODE=paper VENUE=paper ENABLE_LIVE_TRADING=0 USE_FAKE_PRICE_FEED=0 \
SYMBOLS=ETH,BTC LIGHTER_SYMBOLS=ETH,BTC docker compose up -d brokerage
# Esperar ~10s
docker compose run --rm brokerage python3 -m application.tools.freqtrade_runner \
  --broker-url http://host.docker.internal:8000 --venue paper --symbol ETH --minutes 15
```
Preus esperats: ETH ~2088$ (coherent amb Lighter web). Execució segueix sent simulada (zero tx).

---

## 2c) LIVE testnet: comparar preus i PnL amb web

**Objectiu:** Validar que els nostres mark_price, unrealized_pnl i realized_pnl coincideixen amb Lighter.

**Comanda:** `./scripts/run_freqtrade_live_testnet.sh 15`

**Què comparar (log vs testnet.app.lighter.xyz):**

| Nostre (log) | Web (Trade History / posició) |
|--------------|--------------------------------|
| `mark_price` (position_pnl) | Preu de marca a la UI |
| `unrealized_pnl` | PnL no realitzat a la posició oberta |
| `realized_pnl` (closed_pnl) | PnL del trade tancat a Trade History |
| `open_price`, `close_price` | Entry / exit del trade a la web |

**Diferències esperables:** Petites per slippage, fees, o timing (nosaltres calculem PnL amb preus del moment; la web pot usar mark/index).

**Fix (2026-02):** Per venue=lighter, ara usem el `unrealized_pnl` oficial de `AccountApi.account()` i derivem el `mark_price` d'aquest. Això fa coincidir els nostres valors amb la web de Lighter.

---

## 2d) Paper risk model (TP/SL/liquidation)

**P3.0:** venue=paper suporta bracket orders i liquidation simulation. Determinista, zero tx.

- **TP/SL triggers:** PaperRiskEngine comprova mark_price cada 1s. LONG: SL si mark≤sl_price, TP si mark≥tp_price. SHORT: invers.
- **Liquidation:** equity = collateral + unrealized_pnl. Si equity ≤ notional × maintenance_margin_ratio → liquidació.
- **Config:** `PAPER_MAINTENANCE_MARGIN_RATIO` (default 0.05), `PAPER_FEE_BPS` (default 0).
- **GET /trades:** inclou `close_reason`: `manual` | `stop_loss` | `take_profit` | `liquidation`.

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
# Suite general (MVP Lighter: core+Lighter, sense gTrade)
./test.sh testing/run_all.py

# Incloure gTrade (opt-in)
./test.sh testing/run_all.py --include-gtrade

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
VENUE=lighter MODE=paper docker compose up -d brokerage
docker compose run --rm brokerage python3 -m application.tools.freqtrade_runner --venue lighter --mode PAPER --symbol ETH --minutes 15
# Log: datafiles/freqtrade_runs/<ts>_ETH_15m.log. Verificar PnL vs Trade History web.

# Paper soak real (2h+, preus Lighter, zero tx)
./scripts/soak_freqtrade_paper_real.sh 120   # 2h mínim
./scripts/soak_freqtrade_paper_real.sh 360   # 6h
# Requereix: .env Lighter. Health gate: exit 2 (positions), 3 (missing_minutes), 4 (market_data_source!=real)

# Freqtrade LIVE testnet (tx reals, comparar preus i PnL amb web)
./scripts/run_freqtrade_live_testnet.sh 15
# Requereix: .env Lighter testnet. Comparar mark_price, realized_pnl del log vs testnet.app.lighter.xyz

# Freqtrade runner venue=paper (zero tx)
./scripts/run_freqtrade_paper.sh 3   # 3 min (script espera broker, preus FAKE)
./scripts/run_freqtrade_paper.sh 15  # 15 min (evidència 2026-02-16: positions_after=0, candles=15)
# Paper amb preus FAKE (sense .env):
MODE=paper VENUE=paper ENABLE_LIVE_TRADING=0 USE_FAKE_PRICE_FEED=1 SYMBOLS=ETH,BTC docker compose up -d brokerage
# Paper amb preus REALS (cal .env Lighter, mark_price ~2088$):
MODE=paper VENUE=paper ENABLE_LIVE_TRADING=0 USE_FAKE_PRICE_FEED=0 SYMBOLS=ETH,BTC LIGHTER_SYMBOLS=ETH,BTC docker compose up -d brokerage
# Esperar ~10s; després (host.docker.internal evita NameResolutionError):
docker compose run --rm brokerage python3 -m application.tools.freqtrade_runner \
  --broker-url http://host.docker.internal:8000 --venue paper --symbol ETH --minutes 15

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
- Freqtrade paper 15 min (preus reals) → market_data_source=real, mark_price ~2088$, positions_after=0 ✅
- Freqtrade paper 15 min (preus fake) → `./scripts/run_freqtrade_paper.sh 15` → positions_after=0, candles=15 ✅ (evidència 2026-02-16)
- Freqtrade LIVE testnet 15 min → comparar preus i PnL amb testnet.app.lighter.xyz
- Paper soak real 120 min+ → `./scripts/soak_freqtrade_paper_real.sh 120` → market_data_source=real, positions_after=0, missing_minutes<=1 ✅ (evidència 20260215_074407_ETH_120m_real.log)

**Referència:** [docs/ESTAT.md](ESTAT.md)
