# Comandes per Demà (2026-02-18) — Anàlisi Ostium

Aquest fitxer té les comandes que has d'executar demà després que el collector acabi.

---

## ⏰ Timeline

### 08:00-10:00 UTC (03:00-05:00 ET) — Probes Qualitat

**1. Verificar que collector ha acabat:**

```bash
tmux list-sessions | grep ostium_24h
```

Si NO apareix = ✅ acabat. Si apareix encara = espera una mica més.

---

**2. Check resum final:**

```bash
cd /mnt/volume-SQ/dev/BrokerageService
./lab/ostium/scripts/check_24h_progress.sh
```

Hauries de veure:
- ~1440 candles per símbol
- 0 duplicats
- 0 gaps (o molt pocs)

---

**3. Executar probes de qualitat:**

```bash
cd /mnt/volume-SQ/dev/BrokerageService

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

**Busca aquests verdicts:**
- ✅ PASS — Data quality is good
- ⚠️ PARTIAL — Some issues found
- ❌ FAIL — Multiple issues

---

### 12:00-14:00 UTC (07:00-09:00 ET) — Compat Dukascopy

⏰ **IMPORTANT:** NO executar abans de les 12:00 UTC! Dukascopy té delay.

---

**4. Executar compat vs Dukascopy:**

```bash
cd /mnt/volume-SQ/dev/BrokerageService

# EUR/USD (prioritari)
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol EURUSD \
  --ostium-dir lab/out/ostium_prices/20260217_080232 \
  --minutes 1440

# XAU/USD (si Dukascopy el suporta)
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol XAUUSD \
  --ostium-dir lab/out/ostium_prices/20260217_080232 \
  --minutes 1440
```

**Busca el VERDICT al final:**
- ✅ **PASS** → Dukascopy compatible per backtest Ostium
- ⚠️ **PARTIAL** → Compatible amb precaució
- ❌ **FAIL** → Massa diferències

---

**5. O executar tot automàticament:**

```bash
cd /mnt/volume-SQ/dev/BrokerageService
./lab/ostium/scripts/run_full_analysis.sh
```

Aquest script:
- ✅ Verifica collector acabat
- ✅ Compta candles
- ✅ Executa tots els probes
- ✅ Executa compat vs Dukascopy (amb warning si abans 12:00)
- ✅ Mostra summary final

---

## 📊 Resultats Esperats

### Probes Qualitat (08:00-10:00)

**EURUSD, XAUUSD, GBPUSD:**
- Candles: ~1440 per símbol
- Missing minutes: ≤2
- Duplicates: 0
- TS step errors: 0
- Max gap: ≤300s
- Zero range ratio: <30%

### Compat Dukascopy (12:00+)

**EURUSD (prioritari):**
- Correlació: >0.7
- Dir agree: >65%
- Mean diff close: <0.001
- Zero range (Ostium): <30%

**Verdict esperat:** PASS o PARTIAL

Si PASS → ✅ Pots usar Dukascopy per històric pre-Ostium en backtest

---

## 📁 Artifacts Finals

Després d'executar tot:

```
lab/out/
├── ostium_prices/20260217_080232/
│   ├── EURUSD.jsonl
│   ├── XAUUSD.jsonl
│   └── GBPUSD.jsonl
├── ostium_price_probe_EURUSD.json
├── ostium_price_probe_XAUUSD.json
├── ostium_price_probe_GBPUSD.json
├── ostium_compat_EURUSD_1440m.json ⭐
└── ostium_compat_XAUUSD_1440m.json
```

---

## 🚨 Troubleshooting

### "No Dukascopy candles found"

**Causa:** Executat massa aviat, delay no passat.

**Solució:** Espera 1-2h més, torna a provar.

### "tmux session still running"

**Causa:** Collector encara no ha acabat les 24h.

**Solució:** Espera o verifica temps restant al STATUS.md.

---

## 📚 Referències

- **Timeline detallada:** `lab/out/ostium_prices/TIMELINE_COMPAT.md`
- **Guia completa:** `lab/out/ostium_prices/README_FINAL.md`
- **Check progrés:** `./lab/ostium/scripts/check_24h_progress.sh`

---

**Preparat per:** 2026-02-18  
**Executar a partir de:** 08:00 UTC (probes) i 12:00 UTC (compat)
