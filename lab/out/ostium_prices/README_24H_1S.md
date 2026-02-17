# Ostium 24h Collection — High Frequency (1s interval)

**Inici:** 2026-02-17 07:57 UTC  
**Duració:** 24 hores  
**Símbols:** EURUSD, XAUUSD (or), GBPUSD  
**Poll interval:** **1 segon per asset**  
**Request rate:** **3 req/s** (1 per cada símbol)  

---

## 🚀 Característiques

**Alta freqüència:**
- 1 consulta per segon per cada asset
- 60 ticks per minut per símbol
- ~86,400 ticks per símbol en 24h
- **259,200 requests totals en 24h**

**Cobertura:** 3 assets en paral·lel (EURUSD, XAUUSD, GBPUSD)

**Qualitat esperada:**
- Candles més precises (60 samples/min vs 6 samples/min amb 10s)
- Millor captura de High/Low intraminut
- Més granularitat per detectar moviments ràpids

---

## 📁 On són les dades?

**Directori:** `lab/out/ostium_prices/20260217_075747/`

**Fitxers:**
- `EURUSD.jsonl` — Candles 1m EUR/USD
- `XAUUSD.jsonl` — Candles 1m or (gold)
- `GBPUSD.jsonl` — Candles 1m GBP/USD
- `state.json` — Estat del collector (restartable)
- `STATUS.md` — Informe actualitzat cada 30s

---

## 🔍 Comanda ràpida

```bash
cd /mnt/volume-SQ/dev/BrokerageService
./lab/ostium/scripts/check_24h_progress.sh
```

---

## 📊 Comandes detallades

### 1. Veure progrés per símbol

```bash
wc -l lab/out/ostium_prices/20260217_075747/*.jsonl
```

**Esperat després de 24h:**
- ~1440 candles per símbol (24h × 60 min)
- Cada candle construïda amb ~60 ticks (1s interval)

### 2. Comparar última candle de cada símbol

```bash
echo "=== EUR/USD ===" && tail -1 lab/out/ostium_prices/20260217_075747/EURUSD.jsonl | jq '.'
echo "=== XAU/USD ===" && tail -1 lab/out/ostium_prices/20260217_075747/XAUUSD.jsonl | jq '.'
echo "=== GBP/USD ===" && tail -1 lab/out/ostium_prices/20260217_075747/GBPUSD.jsonl | jq '.'
```

### 3. Veure OUTPUT en temps real

```bash
tmux attach -t ostium_collector_1s
```

**Per sortir:** `Ctrl+B` després `D` (detach)

### 4. Veure log complet

```bash
tail -f lab/out/ostium_prices/../ostium_24h_1s_3assets.log
```

---

## 📊 Test de Rate Limit (ja executat)

✅ **Test 3 minuts:** 540 requests (3 req/s × 180s)  
✅ **0 errors 429** — Rate limit OK  
✅ **Test 24h estimat:** 259,200 requests sense problemes  

---

## 📈 Comparació 10s vs 1s interval

| Interval | Ticks/candle | Requests/24h | Millora H/L | Cost |
|----------|--------------|--------------|-------------|------|
| **10s** | 6 | 25,920 | Bàsic | 1× |
| **1s** | 60 | 259,200 | **10× millor** | 10× |

**Exemple de millora captura High/Low:**

**10s interval:**
```json
{"ts": 1771315080, "o": 1.18320, "h": 1.18325, "l": 1.18315, "c": 1.18324}
```

**1s interval:**
```json
{"ts": 1771315080, "o": 1.18315, "h": 1.18327, "l": 1.18315, "c": 1.18324}
```

Captura High més alt: $1.18327 vs $1.18325 (+$0.00002)

---

## 📊 Validació després de 24h

### Executar probes per cada símbol

```bash
# EUR/USD
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/20260217_075747 \
  --check-trading-hours

# XAU/USD (or)
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol XAUUSD \
  --indir lab/out/ostium_prices/20260217_075747 \
  --check-trading-hours

# GBP/USD
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol GBPUSD \
  --indir lab/out/ostium_prices/20260217_075747 \
  --check-trading-hours
```

### Mètriques clau (esperats)

| Mètrica | Esperat | Notes |
|---------|---------|-------|
| `missing_minutes` | ≤2 | Acceptable gaps |
| `duplicates` | 0 | Dedup per ts |
| `ts_step_errors` | 0 | Candles cada 60s |
| `max_gap_s` | ≤300 | Max 5 min gap |
| `zero_range_ratio` | <30% | % candles H==L |

---

## 🛑 Aturar el collector

### Opció 1: Aturar correctament (recomanat)

```bash
tmux attach -t ostium_collector_1s
# Prem Ctrl+C (flush automàtic)
```

### Opció 2: Matar sessió tmux

```bash
tmux kill-session -t ostium_collector_1s
```

---

## ⏱️ Timeline

**Inici:** 2026-02-17 07:57 UTC  
**Fi (estimada):** 2026-02-18 07:57 UTC  

**Check si ha acabat:**
```bash
tmux list-sessions | grep ostium_collector_1s
```

---

## 💡 Per què 1s interval?

### Pros
- ✅ **10× més granularitat** (60 vs 6 ticks/min)
- ✅ **Millor captura H/L** intraminut
- ✅ **Sense rate limits** (test validat)
- ✅ **Més precisió** per backtest

### Contras
- ⚠️ **10× més requests** (259k vs 26k)
- ⚠️ **Més càrrega** al servidor Ostium
- ⚠️ **Molts ticks repetits** (API no canvia cada segon)

### Recomanació
- **1s interval** per captures crítiques (24-72h)
- **5s interval** per captures llargues (1-2 setmanes)
- **10s interval** per monitorització contínua (>1 mes)

---

## 📁 Artifacts finals esperats

Després de 24h:

```
lab/out/ostium_prices/20260217_075747/
├── EURUSD.jsonl          (~1440 candles, ~86k ticks capturats)
├── XAUUSD.jsonl          (~1440 candles, ~86k ticks capturats)
├── GBPUSD.jsonl          (~1440 candles, ~86k ticks capturats)
├── state.json            (última ts per resumir)
└── STATUS.md             (informe final)
```

**Probe reports:**
```
lab/out/
├── ostium_price_probe_EURUSD.json
├── ostium_price_probe_XAUUSD.json
└── ostium_price_probe_GBPUSD.json
```

---

## 🔬 Anàlisi de Qualitat (post-24h)

### Comparar ranges H-L entre intervals

```bash
# Calcular rang mitjà (H-L) per cada símbol
echo "=== EURUSD range analysis ===" 
cat lab/out/ostium_prices/20260217_075747/EURUSD.jsonl | jq -r '.h - .l' | awk '{sum+=$1; count++} END {print "Mean range:", sum/count, "pips:", sum/count*10000}'

echo "=== XAUUSD range analysis ===" 
cat lab/out/ostium_prices/20260217_075747/XAUUSD.jsonl | jq -r '.h - .l' | awk '{sum+=$1; count++} END {print "Mean range:", sum/count, "$"}'

echo "=== GBPUSD range analysis ===" 
cat lab/out/ostium_prices/20260217_075747/GBPUSD.jsonl | jq -r '.h - .l' | awk '{sum+=$1; count++} END {print "Mean range:", sum/count, "pips:", sum/count*10000}'
```

---

## 📚 Referències

- **Investigació tècnica:** `docs/LAB_OSTIUM_PRICE_MONITORING.md`
- **Script collector:** `lab/ostium/scripts/rest_price_collector.py`
- **Script probe:** `lab/ostium/scripts/rest_price_probe.py`
- **API Ostium:** https://ostium-labs.gitbook.io/ostium-docs/developer/api-and-sdk

---

**Last updated:** 2026-02-17 07:59 UTC  
**Status:** ✅ Collector actiu (tmux: ostium_collector_1s)
