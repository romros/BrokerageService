# Timeline: Ostium vs Dukascopy Compat

## 📅 Quan podrem comparar Ostium amb Dukascopy?

### Problema: Dukascopy Delay

Dukascopy **NO publica dades en temps real**. Tenen un delay típic de:
- **~1-4 hores** per forex majors (EURUSD, GBPUSD)
- **Fins a 24h** per alguns instruments menys líquids

---

## ⏱️ Timeline Detallada

### Dia 1: 2026-02-17 (Avui)

**08:02 UTC — Inici captura Ostium**
- ✅ Collector llançat (3 assets: EURUSD, XAUUSD, GBPUSD)
- ✅ Poll interval: 2 segons
- ⏳ Capturant preus en temps real

**Dukascopy en aquest moment:**
- ⏳ Encara no té dades d'avui disponibles
- Última dada disponible: ~08:00 UTC - 4h = **04:00 UTC** (aprox)

---

### Dia 2: 2026-02-18 (Demà)

**08:02 UTC — Fi captura Ostium**
- ✅ 24h completades
- ✅ ~1440 candles per símbol
- ✅ Executar probes qualitat Ostium

**Dukascopy en aquest moment:**
- ⏳ Encara NO té les dades del rang complet
- Última dada disponible: ~08:00 UTC - 4h = **04:00 UTC** (4h abans)
- ❌ **Falta el final del rang** (04:00→08:02)

**12:00-14:00 UTC — Dades Dukascopy disponibles** ✅
- ✅ Dukascopy ja té dades de 08:02→08:02 del dia anterior
- ✅ **PODEM COMPARAR!**
- ✅ Executar compat probe

---

## 🎯 Recomanació

### ⏰ MILLOR MOMENT per executar compat:

**2026-02-18 a les 12:00-14:00 UTC (07:00-09:00 ET)**

**Per què?**
- ✅ Collector Ostium finalitzat (08:02 d'avui)
- ✅ Dukascopy delay passat (~4h)
- ✅ Rang complet disponible a Dukascopy

---

## 📊 Com executar la comparació

### Pas 1: Verificar collector finalitzat

```bash
tmux list-sessions | grep ostium_24h
# Si no apareix = collector acabat ✅
```

### Pas 2: Executar probes qualitat Ostium (08:00-10:00 UTC)

```bash
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/20260217_080232 \
  --check-trading-hours
```

### Pas 3: Esperar fins 12:00-14:00 UTC

⏳ **IMPORTANT:** NO executar abans! Dukascopy no tindrà les dades.

### Pas 4: Executar compat probe (12:00+ UTC)

```bash
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol EURUSD \
  --ostium-dir lab/out/ostium_prices/20260217_080232 \
  --minutes 1440
```

**Output esperat:**
- Correlació preus (`corr_at_lag0`)
- Direction agreement (`dir_agree_pct`)
- Quality metrics (`zero_range_ratio`)
- Verdict: PASS/PARTIAL/FAIL

---

## 📈 Exemple de Verdict

### ✅ PASS (Ideal)

```
✅ PASS — Dukascopy és compatible per backtest d'Ostium
   Correlació: 0.85 >0.7 ✅
   Dir agree: 72.3% >65% ✅
   Zero range: 18.2% <30% ✅
```

**Significa:** Pots usar Dukascopy com a font històrica per backtest d'estratègies Ostium.

### ⚠️ PARTIAL

```
⚠️  PARTIAL — Compatible amb precaució
   Correlació: 0.76 ✅
   Dir agree: 68.5% ✅
   Zero range: 35.1% ⚠️
```

**Significa:** Hi ha algunes diferències, però acceptables. Revisar zero_range.

### ❌ FAIL

```
❌ FAIL — Massa diferències, revisar fonts
   Correlació: 0.42 ❌
   Dir agree: 54.2% ❌
```

**Significa:** Ostium i Dukascopy usen fonts diferents o hi ha problemes de qualitat.

---

## 🚨 Troubleshooting

### "No Dukascopy candles found for this range"

**Causa:** Dades encara no disponibles.

**Solució:**
1. Espera 1-2 hores més
2. Torna a executar compat probe
3. Si persisteix, pot ser weekend/market closed

### "Dukascopy delay: data not yet available"

**Causa:** Executat massa aviat.

**Solució:** Espera fins 12:00-14:00 UTC mínim.

---

## 📁 Artifacts Finals

Després de completar compat (2026-02-18, 14:00+ UTC):

```
lab/out/
├── ostium_prices/20260217_080232/
│   ├── EURUSD.jsonl               (Ostium raw)
│   ├── XAUUSD.jsonl
│   └── GBPUSD.jsonl
├── ostium_price_probe_EURUSD.json (Qualitat Ostium)
├── ostium_price_probe_XAUUSD.json
├── ostium_price_probe_GBPUSD.json
└── ostium_compat_EURUSD_1440m.json (Compat vs Dukascopy) ⭐
```

---

**Resum:**
- ✅ **Avui (17):** Captura Ostium en marxa
- ⏳ **Demà (18) 08:00:** Captura finalitza, probes qualitat
- ✅ **Demà (18) 12:00+:** Compat vs Dukascopy disponible

---

**Last updated:** 2026-02-17 08:05 UTC
