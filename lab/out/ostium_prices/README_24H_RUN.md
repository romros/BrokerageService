# Ostium 24h Price Collection — README

**Inici:** 2026-02-17 07:41 UTC  
**Duració:** 24 hores  
**Símbol:** EURUSD  
**Poll interval:** 10 segons  

---

## 📁 On són les dades?

**Directori:** `lab/out/ostium_prices/20260217_074118/`

**Fitxers:**
- `EURUSD.jsonl` — Candles 1m (una línia per candle)
- `state.json` — Estat del collector (per resumir)
- `STATUS.md` — Informe de progrés actualitzat cada 30s

---

## 🔍 Comandes per revisar el progrés

### 1. Veure quantes candles s'han capturat

```bash
wc -l lab/out/ostium_prices/20260217_074118/EURUSD.jsonl
```

**Esperat:** ~1440 candles (24h × 60 min)

### 2. Veure STATUS report

```bash
cat lab/out/ostium_prices/20260217_074118/STATUS.md
```

Mostra:
- Candles capturades
- Última timestamp
- Gaps (si n'hi ha)
- Duplicats (hauria de ser 0)

### 3. Veure últimes 10 candles

```bash
tail -10 lab/out/ostium_prices/20260217_074118/EURUSD.jsonl | jq '.'
```

### 4. Veure primera i última candle

```bash
# Primera
head -1 lab/out/ostium_prices/20260217_074118/EURUSD.jsonl | jq '.'

# Última
tail -1 lab/out/ostium_prices/20260217_074118/EURUSD.jsonl | jq '.'
```

### 5. Veure output en temps real (tmux)

```bash
tmux attach -t ostium_collector
```

**Per sortir sense aturar:** Prem `Ctrl+B` i després `D` (detach)

---

## 📊 Validar qualitat de les dades (després de 24h)

Un cop completada la captura, executa el probe:

```bash
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/20260217_074118 \
  --check-trading-hours
```

**Mètriques clau:**
- `missing_minutes` — Hauria de ser ≤2 (acceptable)
- `duplicates` — Hauria de ser 0
- `ts_step_errors` — Hauria de ser 0 (candles cada 60s)
- `max_gap_s` — Hauria de ser ≤300s (5 min)
- `zero_range_ratio` — Hauria de ser <30% (candles amb H==L)

---

## 🛑 Com aturar el collector

### Opció 1: Aturar-lo correctament (recomanat)

```bash
# Attach a la sessió
tmux attach -t ostium_collector

# Prem Ctrl+C (el script farà flush de les candles restants)
```

### Opció 2: Matar la sessió tmux

```bash
tmux kill-session -t ostium_collector
```

**Nota:** El collector és restartable. Si es talla, pots resumir amb `--resume 1` (default).

---

## 📈 Exemple de format candle

```json
{
  "ts": 1771314060,      // Timestamp start-of-minute (epoch UTC)
  "o": 1.1833,           // Open (primer preu del minut)
  "h": 1.18332,          // High (màxim del minut)
  "l": 1.1833,           // Low (mínim del minut)
  "c": 1.18332,          // Close (últim preu del minut)
  "v": 0                 // Volume (N/A per polling REST)
}
```

---

## ⏱️ Temps estimat de finalització

**Inici:** 2026-02-17 07:41 UTC  
**Fi (estimada):** 2026-02-18 07:41 UTC  

**Comprovar si ha acabat:**

```bash
# Si la sessió tmux ja no existeix, vol dir que ha acabat
tmux list-sessions | grep ostium_collector
```

---

## 📁 Artifacts finals

Després de 24h, tindràs:

- `EURUSD.jsonl` — ~1440 candles (24h × 60 min)
- `state.json` — Estat final
- `STATUS.md` — Informe final
- **Probe report:** `lab/out/ostium_price_probe_EURUSD.json` (després d'executar probe)

---

**Last updated:** 2026-02-17 07:42 UTC
