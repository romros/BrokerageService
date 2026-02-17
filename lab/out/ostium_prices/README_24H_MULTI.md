# Ostium 24h Multi-Symbol Price Collection

**Inici:** 2026-02-17 07:48 UTC  
**Duració:** 24 hores  
**Símbols:** EURUSD, XAUUSD (or), GBPUSD  
**Poll interval:** 10 segons  

---

## 📁 On són les dades?

**Directori:** `lab/out/ostium_prices/20260217_074849/`

**Fitxers:**
- `EURUSD.jsonl` — Candles 1m EUR/USD
- `XAUUSD.jsonl` — Candles 1m or (gold)
- `GBPUSD.jsonl` — Candles 1m GBP/USD
- `state.json` — Estat del collector (per resumir)
- `STATUS.md` — Informe de progrés actualitzat cada 30s

---

## 🔍 Comanda ràpida per revisar el progrés

```bash
cd /mnt/volume-SQ/dev/BrokerageService
./lab/ostium/scripts/check_24h_progress.sh
```

**Mostra:**
- Estat de la sessió tmux
- Candles capturades per cada símbol
- STATUS.md complet
- Últimes candles de cada símbol

---

## 📊 Comandes detallades

### 1. Veure quantes candles per símbol

```bash
wc -l lab/out/ostium_prices/20260217_074849/*.jsonl
```

**Esperat després de 24h:**
- ~1440 candles per símbol (24h × 60 min)

### 2. Veure STATUS report

```bash
cat lab/out/ostium_prices/20260217_074849/STATUS.md
```

### 3. Veure últimes 5 candles de cada símbol

```bash
# EUR/USD
tail -5 lab/out/ostium_prices/20260217_074849/EURUSD.jsonl | jq '.'

# Or (XAU)
tail -5 lab/out/ostium_prices/20260217_074849/XAUUSD.jsonl | jq '.'

# GBP/USD
tail -5 lab/out/ostium_prices/20260217_074849/GBPUSD.jsonl | jq '.'
```

### 4. Comparar preus entre símbols

```bash
# Últimes candles dels 3 símbols
echo "=== EUR/USD ===" && tail -1 lab/out/ostium_prices/20260217_074849/EURUSD.jsonl | jq '{ts, close: .c}'
echo "=== XAU/USD ===" && tail -1 lab/out/ostium_prices/20260217_074849/XAUUSD.jsonl | jq '{ts, close: .c}'
echo "=== GBP/USD ===" && tail -1 lab/out/ostium_prices/20260217_074849/GBPUSD.jsonl | jq '{ts, close: .c}'
```

### 5. Veure output en temps real (tmux)

```bash
tmux attach -t ostium_collector_multi
```

**Per sortir sense aturar:** Prem `Ctrl+B` i després `D` (detach)

---

## 📊 Validar qualitat de les dades (després de 24h)

Executa el probe per cada símbol:

```bash
# EUR/USD
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/20260217_074849 \
  --check-trading-hours

# XAU/USD (or)
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol XAUUSD \
  --indir lab/out/ostium_prices/20260217_074849 \
  --check-trading-hours

# GBP/USD
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol GBPUSD \
  --indir lab/out/ostium_prices/20260217_074849 \
  --check-trading-hours
```

**Mètriques clau a validar:**
- `missing_minutes` ≤2 per símbol
- `duplicates` == 0
- `ts_step_errors` == 0
- `max_gap_s` ≤300s
- `zero_range_ratio` <30%

---

## 🛑 Com aturar el collector

### Opció 1: Aturar correctament (recomanat)

```bash
# Attach a la sessió
tmux attach -t ostium_collector_multi

# Prem Ctrl+C (el script farà flush de les candles restants)
```

### Opció 2: Matar la sessió tmux

```bash
tmux kill-session -t ostium_collector_multi
```

---

## 📈 Exemple de preus capturats

```json
// EUR/USD
{"ts": 1771314540, "o": 1.18323, "h": 1.18323, "l": 1.18319, "c": 1.18322, "v": 0}

// XAU/USD (or)
{"ts": 1771314540, "o": 4917.767, "h": 4917.767, "l": 4915.468, "c": 4915.482, "v": 0}

// GBP/USD
{"ts": 1771314540, "o": 1.35581, "h": 1.35581, "l": 1.35562, "c": 1.35563, "v": 0}
```

---

## ⏱️ Temps estimat de finalització

**Inici:** 2026-02-17 07:48 UTC  
**Fi (estimada):** 2026-02-18 07:48 UTC  

**Comprovar si ha acabat:**

```bash
# Si la sessió tmux ja no existeix, vol dir que ha acabat
tmux list-sessions | grep ostium_collector_multi
```

---

## 💡 Notes sobre els símbols

### EURUSD (Euro / Dòlar USA)
- Parell més líquid del món forex
- Trading hours RWA: Mo-Fr 04:00-20:00 ET
- Weekends tancats

### XAUUSD (Or / Dòlar USA)
- Commodity (metall preciós)
- Trading hours RWA: Mo-Fr (similar forex)
- Preu en $/onça troy

### GBPUSD (Lliura Esterlina / Dòlar USA)
- Conegut com "Cable"
- Trading hours RWA: Mo-Fr 04:00-20:00 ET
- Weekends tancats

---

## 📁 Artifacts finals esperats

Després de 24h, tindràs per **cada símbol**:

- `<SYMBOL>.jsonl` — ~1440 candles (24h × 60 min)
- **Probe reports:** 
  - `lab/out/ostium_price_probe_EURUSD.json`
  - `lab/out/ostium_price_probe_XAUUSD.json`
  - `lab/out/ostium_price_probe_GBPUSD.json`

---

## ❓ Si vols afegir més símbols

Atura el collector i relança amb més símbols:

```bash
# Aturar actual
tmux kill-session -t ostium_collector_multi

# Llançar amb més símbols (exemple: afegir USDJPY)
cd /mnt/volume-SQ/dev/BrokerageService
tmux new-session -d -s ostium_collector_multi \
  "python3 lab/ostium/scripts/rest_price_collector.py \
   --symbols EURUSD,XAUUSD,GBPUSD,USDJPY \
   --hours 24 \
   --poll-interval-s 10 \
   --outdir lab/out/ostium_prices \
   2>&1 | tee lab/out/ostium_24h_multi.log"
```

**Símbols disponibles a Ostium:**
- Forex: EUR/USD, GBP/USD, AUD/USD, NZD/USD, USD/JPY, USD/CAD, USD/CHF, USD/MXN
- Metalls: XAU/USD (or), XAG/USD (plata), XPT/USD (platí), XPD/USD (pal·ladi)
- Crypto: BTC/USD, ETH/USD, SOL/USD, ADA/USD, LINK/USD, etc.
- Stocks: AAPL/USD, TSLA/USD, NVDA/USD, MSFT/USD, etc.
- Índexs: SPX/USD, NDX/USD, DJI/USD, DAX/EUR, etc.

---

**Last updated:** 2026-02-17 07:51 UTC
