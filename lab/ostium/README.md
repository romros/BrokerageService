# Ostium Lab

> **Venue canònic del projecte** (Ostium-first, T5.32).  
> LAB per validació avançada (compat, fees, mainnet). Producció: `./scripts/up_ostium_live.sh`.

---

## Status

### Trading (2026-02-11)

**Scripts validats:**
- `test_full_cycle_no_subgraph.py` — Open/close sense subgraph (workaround brute force)
- `test_multicall_optimized.py` — Multicall3 optimization (9.6× més ràpid, 1 RPC vs 10)
- `test_market_fees.py` — Fees ~$0.56/RT (45× més barat que gTrade)

**Conclusió:** Viable testnet. Mainnet pendent.

**Docs:** [RESULTS.md](RESULTS.md)

### Price Monitoring (2026-02-17)

**Scripts creats:**

| Script | Funció | Status |
|--------|--------|--------|
| `rest_price_collector.py` | Polling REST, build candles 1m | ✅ Continu (default --forever) |
| `rest_price_probe.py` | Valida qualitat (gaps, coverage) | ✅ |
| `ostium_vs_dukascopy_compat_v2.py` | Compara Ostium vs Dukascopy | ✅ |
| `check_24h_progress.sh` | Check progrés | ✅ |

**Resultats finals (2026-02-18, 24h captura):**

| Símbol | Candles | Corr | Dir agree | Veredicte |
|--------|---------|------|-----------|-----------|
| **EURUSD** | 1440 | 0,95 | 88,5% | **PASS** |
| **XAUUSD** | 1340 | 0,43 | 92,1% | FAIL |

- EURUSD: Dukascopy compatible per backtest Ostium (ostium_primary_allowed=true)
- XAUUSD: Correlació baixa, max diff ~163$ — revisar instrument/offset

**Timestamp alignment verificat:**
- UTC start-of-minute (:00s)
- 0 desplaçament temporal
- Sincronitzat amb Dukascopy

**Conclusió:**
- Ostium NO té històric/WS
- Solució: REST polling + Dukascopy backfill
- Compatibilitat confirmada (alta confiança)

**Docs:** [../../docs/LAB_OSTIUM_PRICE_MONITORING.md](../../docs/LAB_OSTIUM_PRICE_MONITORING.md)

---

## 🚀 Quick Start

**Env:** El lab usa el `.env` de l’arrel del repo com a font de veritat. No cal `lab/ostium/.env` si executeu des de l’arrel (Docker o `./test.sh` amb variables a l’arrel). Per execució local dins `lab/ostium`: `cp .env.example .env` i editar.

### Trading (Testnet)

```bash
# 1. Setup (arrel repo: .env amb PRIVATE_KEY; o dins lab/ostium: cp .env.example .env)
# 2. Full cycle test (local)
python3 scripts/test_full_cycle_no_subgraph.py
```

**Tancar posició oberta (des del repo root):**  
El mateix `.env` (o `PRIVATE_KEY`/`OSTIUM_PRIVATE_KEY` a l’arrel) s’usa per llistar i tancar posicions. `./test.sh` carrega `lab/ostium/.env` quan el script és sota `lab/ostium`.

```bash
# Des del directori arrel del projecte
./test.sh lab/ostium/scripts/close_open_position.py --symbol BTCUSD --dry-run   # només llistar
./test.sh lab/ostium/scripts/close_open_position.py --symbol BTCUSD             # tancar
./test.sh lab/ostium/scripts/close_open_position.py --all --dry-run              # llistar totes
```

### Smoke LIVE via API (split compose)

**Canònic:** [docs/ESTAT.md](../../docs/ESTAT.md) § Ostium LIVE.

- **Run:** `./scripts/up_ostium_live.sh`
- **Smoke only:** `./scripts/run_ostium_live_smoke.sh --recreate --clean`

Regla: NO aturar ni recrear `realtime_datalayer`.

### Price Monitoring

**Canònic (recomanat):** servei supervisat amb restart policy

```bash
# 1. Start monitor (restart unless-stopped, rotació diària, retenció 14 dies)
./scripts/run_lab.sh ostium-monitor start

# 2. Status (last_ts per símbol, gaps, dupes, market_open)
./scripts/run_lab.sh ostium-monitor status

# 3. Logs
./scripts/run_lab.sh ostium-monitor logs

# 4. Stop
./scripts/run_lab.sh ostium-monitor stop
```

**Fallback (tmux manual):**

```bash
tmux new -d -s ostium_24h \
  "python3 scripts/rest_price_collector.py --poll-interval-s 2 --forever --enable-daily-rotation"
```

**Check progrés (manual):**
```bash
./scripts/check_24h_progress.sh

# 3. Comparació Dukascopy (Docker)
cd ../..
docker run --rm -v $(pwd):/workspace -w /workspace \
  -e PYTHONPATH=/workspace ostium_analysis \
  python3 lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py \
    --symbol EURUSD \
    --ostium-dir lab/out/ostium_prices/continuous \
    --candles 1440
```

---

## Ús amb Docker (projecte aïllat lab_ostium)

**Regla:** Totes les comandes del lab han d’usar `-p lab_ostium` per no afectar el stack prod (realtime, etc.). Prohibit `docker compose down` sense `-p lab_ostium`.

- **Aixecar contenidor (bind mount; edició al host sense rebuild):**
  ```bash
  # Des de l’arrel del repo (el compose llegeix .env de l’arrel)
  docker compose -p lab_ostium up -d ostium-cli
  ```

- **Executar scripts amb env del root (canvis al codi es reflecteixen sense rebuild):**
  ```bash
  docker compose -p lab_ostium run --rm ostium-cli python3 scripts/test_full_cycle_no_subgraph.py
  # Amb variables explícites (opcional):
  docker compose -p lab_ostium run --rm -e PRIVATE_KEY="$PRIVATE_KEY" -e RPC_URL="$RPC_URL" ostium-cli python3 scripts/test_full_cycle_no_subgraph.py
  ```

- **Netejar només el lab:**
  ```bash
  docker compose -p lab_ostium down --remove-orphans
  ```

---

## Runbook (canonical)

Comandes canòniques per E2E i neteja (chain-based, sense subgraph). Des de l’arrel del repo.

**E2E full cycle:**
```bash
docker compose -p lab_ostium run --rm \
  -e PRIVATE_KEY="$PRIVATE_KEY" -e RPC_URL="$RPC_URL" \
  -e SCAN_ONLY=0 -e SANITY_CHECK=1 \
  -e PAIR_ID=2 -e INDEX_BASE=0 -e MAX_ATTEMPTS=64 -e ORACLE_WAIT_S=30 \
  ostium-cli python3 scripts/test_full_cycle_multicall.py
```

**Neteja (scan-only, sense PK):**
```bash
docker compose -p lab_ostium run --rm \
  -e RPC_URL="$RPC_URL" \
  -e TRADER_ADDRESS="$TRADER_ADDRESS" \
  -e SCAN_ONLY=1 -e PAIR_ID=2 -e INDEX_BASE=0 -e MAX_ATTEMPTS=64 \
  ostium-cli python3 scripts/close_all_open_trades.py
```

**Neteja (close real, limitat):**
```bash
docker compose -p lab_ostium run --rm \
  -e RPC_URL="$RPC_URL" -e PRIVATE_KEY="$PRIVATE_KEY" \
  -e SCAN_ONLY=0 -e PAIR_ID=2 -e INDEX_BASE=0 -e MAX_ATTEMPTS=64 \
  -e MAX_CLOSE=1 \
  ostium-cli python3 scripts/close_all_open_trades.py
```

Legacy / subgraph-dependent scripts are archived in `lab/ostium/_archive/`.

---

## Descobriments

### Trading
- ✅ Fees: ~$0.56/RT (45× gTrade)
- ⚠️ Subgraph buit → workaround brute force (10 RPC)
- ✅ Multicall3 optimization: 1 RPC (9.6× ràpid)

### Price Data
- ❌ NO històric, NO WebSocket, NO subgraph útil
- ✅ REST `/latest-price` OK (polling 2s viable)
- ✅ Dukascopy compatible (corr 0.976, dir 92.7%)
- ✅ Timestamp UTC start-of-minute, 0 desplaçament

---

## Estructura i inventari de scripts

```
lab/ostium/
├── README.md                              (aquest fitxer)
├── RESULTS.md                             (trading validació)
├── COMANDES_DEMA.md                       (workflow anàlisi)
├── Dockerfile, docker-compose.yml         (entorn trading)
├── Dockerfile.analysis                    (entorn comparació compat)
└── scripts/
    │
    │  — PRICE MONITORING —
    ├── rest_price_collector.py            ✅ Polling REST, build candles 1m (--forever, rotació diària)
    ├── rest_price_probe.py                ✅ Valida qualitat dades (gaps, coverage, dupes)
    ├── check_24h_progress.sh             ✅ Check ràpid progrés captura 24h
    ├── monitor_status.py                  ✅ Estat monitor (last_ts, gaps, market_open per símbol)
    │
    │  — COMPAT (Ostium vs Dukascopy) —
    ├── ostium_vs_dukascopy_compat_v2.py   ✅ Comparació completa (corr, dir_agree, max_diff)
    ├── ostium_vs_dukascopy_compat.py      ⚠️  Versió anterior (obsoleta; usar v2)
    ├── compat_partial_simple.py           ✅ Compat parcial (menys candles, debug ràpid)
    ├── quick_compat_check.py              ✅ Compat exprés (sense Docker, local)
    ├── check_ostium_quality.py            ✅ Qualitat dades Ostium (noise, outliers)
    ├── run_full_analysis.sh               ✅ Pipeline compat complet (captura + comparació)
    ├── run_compat_tomorrow.sh             ✅ Programa compat per demà
    ├── simple_compat_6h.sh                ✅ Compat ràpid 6h (sense esperar 24h)
    │
    │  — TRADING (Testnet) —
    ├── open_wait_close_btc.py             ✅ Obrir posició → esperar N s → tancar (default BTC 10s)
    ├── close_open_position.py             ✅ Llistar/tancar posicions obertes (--symbol, --all, --dry-run)
    ├── test_full_cycle_no_subgraph.py     ✅ Open/close sense subgraph (workaround brute force)
    ├── test_full_cycle_multicall.py       ✅ Full cycle canònic: open→wait→find→close (multicall + tradingStorage)
    ├── _archive/scripts/test_full_cycle.py   (legacy, depèn del subgraph; arxivat)
    ├── test_multicall_optimized.py        ✅ Multicall3: 1 RPC vs 10 (9.6× ràpid)
    ├── test_market_fees.py                ✅ Fees ~$0.56/RT (45× més barat que gTrade)
    ├── test_limit_with_abi.py             ✅ Test limit orders via ABI
    ├── test_subgraph_quick.py             ✅ Subgraph consulta ràpida
    ├── test_subgraph_historical.py        ✅ Subgraph historial (buit → workaround)
    └── test_subgraph_mainnet_deep.py      ✅ Subgraph mainnet deep scan
```

---

## Path to Production

**Progrés:**
1. **Trading mainnet:** Validar fees/latency real (ara només testnet)
2. **Compat PASS EURUSD:** ✅ Aconseguit (1440c, corr 0.95, dir_agree 88.5%)
3. **Compat XAUUSD:** ❌ FAIL (corr 0.43) — pendent investigar
4. **Infra monitoring:** Validar polling 2s estable 72h+

**Connexió amb prod-ish registry:** Els resultats LAB (compat report) es graduen a prod-ish via `./scripts/run_compat.sh ostium EURUSD` o `./scripts/run_soak.sh 2 ostium post-compat`. El tool escriu `datafiles/compat_reports/ostium_compat_registry.json`; si PASS → `ostium_primary_allowed=true` per aquell símbol. Font de veritat: `get_ostium_primary_allowed(symbol)`.

### Runner exploration (T8.* — paritat MT4/SQ)

Els exploratoris de backtest i paritat amb StrategyQuant/MT4 viuen a `lab/runner/` i **segueixen les regles de lab/ostium**: no anar a producció fins que l'exemple funcioni bé.

**Exploració actual (T8.37):** Apply t836_best signal_def (RSI ema_gains sobre typical) + revalidació end-to-end.

```bash
# Pipeline complet: export indicadors t836_best + backtest + trade diff
./scripts/oneshot/run_t837_t836_best_e2e.sh [--force-export]
```

**Docs:** [lab/runner/out_compare/compare_notes.md](../runner/out_compare/compare_notes.md), [docs/ESTAT.md](../../docs/ESTAT.md) § T8.37.

**Regla:** Quan matched/category_counts millorin prou → graduar a policy; si no → documentar i seguir explorant.

---

### Backtest (futur)
- Real-time: Ostium REST polling
- Històric: Dukascopy backfill (si compat PASS)

---

## Captura Actual (continu)

| Paràmetre | Valor |
|-----------|-------|
| Assets | EURUSD, XAUUSD, GBPJPY |
| Mode | Indefinit (append a `continuous/`) |
| Poll | 2s (1.5 req/s) |
| Servei | `./scripts/run_lab.sh ostium-monitor start` (canònic) |
| Output | `lab/out/ostium_prices/continuous/` + `daily/YYYYMMDD/` |
| Rotació | Diària; `daily/LATEST_RUN.txt` pointer |
| Retenció | `OSTIUM_LAB_RETENTION_DAYS=14` (default) |
| Compat Dukascopy | EURUSD, XAUUSD (GBPJPY no suportat per Dukascopy) |

**Nota:** Dukascopy només suporta EURUSD i XAUUSD. GBPJPY es recull per mostra addicional.

---

## Documentació

- [LAB_OSTIUM_PRICE_MONITORING.md](../../docs/LAB_OSTIUM_PRICE_MONITORING.md) — Investigació tècnica
- [RESULTS.md](RESULTS.md) — Trading validació
- [COMANDES_DEMA.md](COMANDES_DEMA.md) — Workflow anàlisi

---

## Comparativa històrica (Lighter arxivat T5.32)

> **Nota:** Lighter arxivat a `_archive/lab/2026-02-legacy-purge/lighter/`. Taula conservada per context històric.

| Criteri | Lighter (legacy arxivat) | Ostium (canònic) |
|---------|--------------------------|------------------|
| Status | Arxivat | ✅ Venue principal |
| Fees | $0.16/RT | $0.56/RT |
| Historical | `/candlestick` | Cal polling REST |
| WebSocket | Sí | ❌ |
| Latest price | REST + WS | REST |
| Assets RWA | EURUSD, XAUUSD | EURUSD, XAUUSD, +molts més |

---

**Última actualització:** 2026-02-24
**Status:** LAB — Captura continua (EURUSD, XAUUSD, GBPJPY → continuous/)
**Índex global:** [docs/INDEX.md](../../docs/INDEX.md)
