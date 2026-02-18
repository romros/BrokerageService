# Ostium Lab (Experimental)

> ⚠️ **LAB EXPERIMENTAL — NO PRODUCCIÓ**  
> Validant si Ostium pot substituir Lighter per RWA (forex/commodities).  
> Si compat PASS + trading OK → candidat per produir.

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

**Primera comparació (388 candles, 6.5h):**
- Correlació: 0.976 (excel·lent)
- Direction agree: 92.7% (molt bo)
- Price diffs: ~0.04 pips (ínfimes)
- Best lag: 0 min (perfecte alignment)
- Veredicte: PARTIAL (amb 1440c → PASS)

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

### Trading (Testnet)

```bash
# 1. Setup
cp .env.example .env
# Editar .env amb PRIVATE_KEY

# 2. Full cycle test
python3 scripts/test_full_cycle_no_subgraph.py
```

### Price Monitoring

```bash
# 1. Captura (3 assets, continu indefinit — default)
tmux new -d -s ostium_24h \
  "python3 scripts/rest_price_collector.py --poll-interval-s 2"

# 2. Check progrés
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

## Estructura

```
lab/ostium/
├── README.md
├── RESULTS.md                             (trading validació)
├── Dockerfile, docker-compose.yml
├── Dockerfile.analysis                    (comparació compat)
└── scripts/
    ├── test_full_cycle_no_subgraph.py     (trading)
    ├── test_multicall_optimized.py        (optimization)
    ├── rest_price_collector.py            (monitoring)
    ├── rest_price_probe.py
    ├── ostium_vs_dukascopy_compat_v2.py   (comparació)
    └── check_24h_progress.sh
```

---

## Path to Production

⚠️ **Pendent validació abans producció:**

1. **Trading mainnet:** Validar fees/latency real (ara només testnet)
2. **Compat PASS:** Aconseguir dir_agree >95% amb 1440c
3. **Infra monitoring:** Validar polling 2s estable 72h+
4. **Comparativa Lighter:** Decidir si val la pena canviar

**Si tot OK → Candidat per substituir Lighter en RWA**

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
| Tmux | ostium_24h |
| Output | `lab/out/ostium_prices/continuous/` |
| Compat Dukascopy | EURUSD, XAUUSD (GBPJPY no suportat per Dukascopy) |

**Nota:** Dukascopy només suporta EURUSD i XAUUSD. GBPJPY es recull per mostra addicional.

---

## Documentació

- [LAB_OSTIUM_PRICE_MONITORING.md](../../docs/LAB_OSTIUM_PRICE_MONITORING.md) — Investigació tècnica
- [RESULTS.md](RESULTS.md) — Trading validació
- [COMANDES_DEMA.md](COMANDES_DEMA.md) — Workflow anàlisi

---

## Comparativa Lighter vs Ostium

| Criteri | Lighter (PRODUCCIÓ) | Ostium (LAB) |
|---------|---------------------|--------------|
| Status | ✅ MVP 100% | 🧪 Experimental |
| Fees | $0.16/RT | $0.56/RT (3.5× més car) |
| Historical | ✅ `/candlestick` | ❌ Cal polling |
| WebSocket | ✅ | ❌ |
| Latest price | REST + WS | REST |
| Monitoring | Native WS | Polling 2s |
| Assets RWA | EURUSD, XAUUSD | EURUSD, XAUUSD, +molts més |
| Data quality | Verificat | En validació |

**Trade-offs:**
- ✅ **Pro Ostium:** Més assets RWA disponibles
- ❌ **Contra Ostium:** Fees més cars, infra menys elegant, no històric

**Decisió:** Pendent validació completa. Si compat PASS + mainnet OK → possible substitució Lighter per RWA.

---

**Última actualització:** 2026-02-18  
**Status:** LAB — Captura continua (EURUSD, XAUUSD, GBPJPY → continuous/)
