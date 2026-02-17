# Ostium 24h Price Collection — FINAL RUN

**Inici:** 2026-02-17 08:02 UTC (03:02 ET)  
**Duració:** 24 hores  
**Símbols:** EURUSD, XAUUSD (or), GBPUSD  
**Poll interval:** **2 segons per asset**  
**Request rate:** **1.5 req/s** (0.5 per símbol)  
**Timezone logs:** **NY time (ET, UTC-5)**  

---

## 🎯 Configuració Final

**Optimització balanç precisió/cost:**
- 2s interval = 30 ticks per minut per símbol
- ~129,600 requests totals en 24h
- Millor que 10s (6 ticks/min) sense excedir com 1s (60 ticks/min)

**Timestamps en NY time:**
- Logs mostren hora Eastern Time (ET)
- Facilita correlació amb trading hours RWA
- Internament ts segueix sent UTC epoch

---

## 📁 Directori de Dades

**Path:** `lab/out/ostium_prices/20260217_080232/`

**Fitxers:**
```
EURUSD.jsonl   — Candles 1m EUR/USD (esperat: ~1440)
XAUUSD.jsonl   — Candles 1m or/USD (esperat: ~1440)
GBPUSD.jsonl   — Candles 1m GBP/USD (esperat: ~1440)
state.json     — Estat restartable
STATUS.md      — Informe cada 30s
```

---

## 🔍 Comandes Ràpides

### Check progrés

```bash
cd /mnt/volume-SQ/dev/BrokerageService
./lab/ostium/scripts/check_24h_progress.sh
```

### Veure output en temps real (NY time)

```bash
tmux attach -t ostium_24h
```

**Per sortir:** `Ctrl+B` després `D`

### Veure últimes candles

```bash
tail -5 lab/out/ostium_prices/20260217_080232/EURUSD.jsonl | jq '.'
tail -5 lab/out/ostium_prices/20260217_080232/XAUUSD.jsonl | jq '.'
tail -5 lab/out/ostium_prices/20260217_080232/GBPUSD.jsonl | jq '.'
```

### Aturar collector

```bash
tmux kill-session -t ostium_24h
```

---

## 📊 Especificacions Tècniques

### Request Rate
- **Per símbol:** 0.5 req/s (1 cada 2s)
- **Total:** 1.5 req/s (3 assets)
- **24h:** ~129,600 requests

### Comparativa intervals

| Interval | Ticks/candle | Req/24h | Cost | Qualitat |
|----------|--------------|---------|------|----------|
| 10s | 6 | 25,920 | Baix | Bàsica |
| **2s** ✅ | **30** | **129,600** | **Mitjà** | **Molt bona** |
| 1s | 60 | 259,200 | Alt | Màxima |

**Conclusió:** 2s és el millor trade-off

### NY Time (ET)
- Logs mostren timestamps en Eastern Time
- Trading hours RWA: Mo-Fr 04:00-20:00 ET
- Facilita debugging durant hores de mercat

---

## ⏱️ Timeline

**Inici:** 2026-02-17 08:02 UTC (03:02 ET)  
**Fi estimada:** 2026-02-18 08:02 UTC (03:02 ET)  

**Check si ha acabat:**
```bash
tmux list-sessions | grep ostium_24h
```

---

## 📊 Validació Post-24h

### 1. Executar probes

```bash
# EUR/USD
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/20260217_080232 \
  --check-trading-hours

# XAU/USD (or)
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol XAUUSD \
  --indir lab/out/ostium_prices/20260217_080232 \
  --check-trading-hours

# GBP/USD
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol GBPUSD \
  --indir lab/out/ostium_prices/20260217_080232 \
  --check-trading-hours
```

### 2. Mètriques esperades

| Mètrica | Target | Notes |
|---------|--------|-------|
| `candles_unique` | ~1440 | 24h × 60 min |
| `missing_minutes` | ≤2 | Gaps acceptables |
| `duplicates` | 0 | Dedup per ts |
| `ts_step_errors` | 0 | Candles cada 60s |
| `max_gap_s` | ≤300 | Max 5 min gap |
| `zero_range_ratio` | <30% | % candles H==L |

### 3. Anàlisi de ranges

```bash
# Rang mitjà H-L per símbol
cat lab/out/ostium_prices/20260217_080232/EURUSD.jsonl | \
  jq -r '.h - .l' | \
  awk '{sum+=$1; count++} END {print "EURUSD mean range:", sum/count*10000, "pips"}'

cat lab/out/ostium_prices/20260217_080232/XAUUSD.jsonl | \
  jq -r '.h - .l' | \
  awk '{sum+=$1; count++} END {print "XAUUSD mean range: $" sum/count}'

cat lab/out/ostium_prices/20260217_080232/GBPUSD.jsonl | \
  jq -r '.h - .l' | \
  awk '{sum+=$1; count++} END {print "GBPUSD mean range:", sum/count*10000, "pips"}'
```

---

## 📁 Artifacts Esperats

Després de 24h completades:

```
lab/out/ostium_prices/20260217_080232/
├── EURUSD.jsonl          (~1440 candles, ~43k ticks)
├── XAUUSD.jsonl          (~1440 candles, ~43k ticks)
├── GBPUSD.jsonl          (~1440 candles, ~43k ticks)
├── state.json            (última ts per resumir)
└── STATUS.md             (informe final)

lab/out/
├── ostium_price_probe_EURUSD.json
├── ostium_price_probe_XAUUSD.json
└── ostium_price_probe_GBPUSD.json
```

---

## 💡 Notes Importants

### Trading Hours (RWA)
- EUR/USD, GBP/USD: Mo-Fr 04:00-20:00 ET
- Weekends tancats (no moviment de preu esperat)
- Probe amb `--check-trading-hours` exclou weekends

### Timestamps
- **Logs:** NY time (ET) per facilitar lectura
- **JSONL:** UTC epoch (estàndard, compatible amb tot)
- **Conversió:** `ts` epoch → datetime UTC → -5h = ET

### Rate Limits
- Validat sense errors 429
- 2s interval conservador i respectuós
- Ostium no publica límits oficials

---

## 📚 Referències

**Documentació:**
- **Investigació completa:** `docs/LAB_OSTIUM_PRICE_MONITORING.md`
- **Script collector:** `lab/ostium/scripts/rest_price_collector.py`
- **Script probe:** `lab/ostium/scripts/rest_price_probe.py`

**API Ostium:**
- Docs: https://ostium-labs.gitbook.io/ostium-docs/developer/api-and-sdk
- Endpoint: `https://metadata-backend.ostium.io/PricePublish/latest-price`

---

## ✅ Checklist Post-Captura

### Dia 1 (2026-02-18, 08:00-10:00 UTC)

- [ ] Esperar 24h completades
- [ ] Verificar tmux session finalitzada
- [ ] Comprovar ~1440 candles per símbol
- [ ] Executar probes (EURUSD, XAUUSD, GBPUSD)
- [ ] Revisar mètriques (missing, gaps, zero_range)
- [ ] Analitzar ranges H-L mitjans

### Dia 1 (2026-02-18, 12:00-14:00 UTC) — Compat vs Dukascopy

⏱️ **IMPORTANT:** Dukascopy té ~1-4h delay. Espera fins migdia per tenir dades disponibles.

```bash
# Executar compat probe Ostium vs Dukascopy (24h EURUSD)
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol EURUSD \
  --ostium-dir lab/out/ostium_prices/20260217_080232 \
  --minutes 1440

# Opcional: XAU i GBP si Dukascopy els suporta
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol XAUUSD \
  --ostium-dir lab/out/ostium_prices/20260217_080232 \
  --minutes 1440
```

**Mètriques compat esperades:**
- `corr_at_lag0` >0.7 (correlació preus)
- `dir_agree_pct` >65% (direcció igual)
- `zero_range_ratio_a` <30% (Ostium qualitat)

- [ ] Executar compat vs Dukascopy
- [ ] Revisar verdict (PASS/PARTIAL/FAIL)
- [ ] Arxivar artifacts si tot OK

---

**Status:** ✅ Collector actiu  
**Tmux session:** `ostium_24h`  
**Last updated:** 2026-02-17 08:03 UTC (03:03 ET)
