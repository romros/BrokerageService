# Ostium Lab — Guia Completa

> **LAB EXPERIMENTAL — NO PRODUCCIÓ**  
> Validant si Ostium pot substituir Lighter per RWA (forex/commodities).  
> Compat PASS + trading OK → candidat per produir.

---

## 1. Context

**Ostium** és un broker RWA (forex/commodities) a Arbitrum. Per servir dades OHLCV per backtest i real-time:

- **Realtime:** Ostium REST `/latest-price` (polling cada 2–10s)
- **Històric/gaps:** Dukascopy backfill (només EURUSD, XAUUSD)

**Problema:** Ostium NO té històric ni WebSocket. Cal capturar preus via polling i validar compatibilitat amb Dukascopy.

---

## 2. Símbols

| Símbol   | Ostium | Dukascopy | Compat probe |
|----------|--------|-----------|--------------|
| EURUSD   | ✅     | ✅        | ✅           |
| XAUUSD   | ✅     | ✅        | ✅           |
| GBPJPY   | ✅     | ❌        | —            |

Dukascopy només suporta EURUSD i XAUUSD. GBPJPY es captura per Ostium però no es pot comparar amb Dukascopy.

---

## 3. Scripts Principals

| Script                         | Funció                                      |
|--------------------------------|---------------------------------------------|
| `rest_price_collector.py`      | Polling REST, construeix candles 1m, JSONL |
| `rest_price_probe.py`          | Valida qualitat (gaps, coverage)            |
| `ostium_vs_dukascopy_compat_v2.py` | Compara Ostium vs Dukascopy             |
| `check_24h_progress.sh`        | Check progrés de la captura                 |
| `run_full_analysis.sh`         | Probes + compat en un sol run               |
| `check_ostium_quality.py`      | Anàlisi qualitat multi-símbol               |
| `simple_compat_6h.sh`          | Quick check 6h                              |

---

## 4. Captura de Dades (Collector)

### Mode continu (recomanat)

El collector corre indefinidament i escriu a `lab/out/ostium_prices/continuous/`:

```bash
cd /mnt/volume-SQ/dev/BrokerageService

# Aturar collector anterior (si n'hi ha)
tmux kill-session -t ostium_24h

# Llançar en mode continu
tmux new -d -s ostium_24h \
  "python3 lab/ostium/scripts/rest_price_collector.py --forever --poll-interval-s 2"
```

**Paràmetres:**
- `--forever` — no s'atura mai, append a `continuous/`
- `--symbols EURUSD,XAUUSD,GBPJPY` — default
- `--poll-interval-s 2` — polling cada 2s per asset

### Mode amb durada fixa

```bash
python3 lab/ostium/scripts/rest_price_collector.py \
  --symbols EURUSD,XAUUSD,GBPJPY \
  --hours 24 \
  --poll-interval-s 2
```

Output: `lab/out/ostium_prices/<YYYYMMDD_HHMMSS>/`

---

## 5. Check Progrés

```bash
./lab/ostium/scripts/check_24h_progress.sh
```

Mostra:
- Si el collector corre (tmux `ostium_24h`)
- Candles per símbol (EURUSD, XAUUSD, GBPJPY)
- STATUS.md
- Últimes candles

**Comandes tmux:**
- Veure output: `tmux attach -t ostium_24h` (sortir: Ctrl+B, D)
- Aturar: `tmux kill-session -t ostium_24h`

---

## 6. Anàlisi de Qualitat

### Probe per símbol

```bash
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/continuous \
  --check-trading-hours
```

### Anàlisi completa (probes + compat)

```bash
./lab/ostium/scripts/run_full_analysis.sh
```

O amb directori explícit:

```bash
./lab/ostium/scripts/run_full_analysis.sh lab/out/ostium_prices/continuous
```

---

## 7. Compat Ostium vs Dukascopy

**Propòsit:** Validar que les dades Ostium són compatibles amb Dukascopy (per backfill de gaps).

**Només EURUSD i XAUUSD** — Dukascopy no té GBPJPY.

### Via test.sh (recomanat)

```bash
./test.sh lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py \
  --symbol EURUSD \
  --ostium-dir lab/out/ostium_prices/continuous \
  --candles 1440
```

### Via Docker

```bash
docker run --rm -v $(pwd):/workspace -w /workspace \
  -e PYTHONPATH=/workspace ostium_analysis \
  python3 lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py \
    --symbol EURUSD \
    --ostium-dir lab/out/ostium_prices/continuous \
    --candles 1440
```

**Verdicts:** PASS | PARTIAL | FAIL (llindars a `compat_report_service`).

**Nota:** Dukascopy té delay ~1–4h. Recomanat executar compat després de les 12:00 UTC.

---

## 8. Directoris i Artifacts

```
lab/out/ostium_prices/
├── continuous/           # Mode --forever (append indefinit)
│   ├── EURUSD.jsonl
│   ├── XAUUSD.jsonl
│   ├── GBPJPY.jsonl
│   ├── state.json
│   └── STATUS.md
└── 20260217_080232/      # Run amb --hours (exemple)
    └── ...

lab/out/
├── ostium_price_probe_<symbol>.json
└── ostium_compat_<symbol>_<N>c.json/
    └── compat_reports/
```

---

## 9. Format de Dades

**JSONL (cada línia = 1 candle):**
```json
{"ts": 1771315860, "o": 1.18314, "h": 1.18316, "l": 1.18312, "c": 1.18315, "v": 0}
```

- `ts` — epoch seconds UTC, start-of-minute
- `o,h,l,c` — OHLC
- `v` — 0 (volume N/A per polling)

---

## 10. Resum de Comandes

```bash
# Captura (continu)
tmux new -d -s ostium_24h "python3 lab/ostium/scripts/rest_price_collector.py --forever --poll-interval-s 2"

# Check
./lab/ostium/scripts/check_24h_progress.sh

# Anàlisi completa
./lab/ostium/scripts/run_full_analysis.sh

# Compat EURUSD
./test.sh lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py --symbol EURUSD --ostium-dir lab/out/ostium_prices/continuous --candles 1440

# Tmux
tmux attach -t ostium_24h    # veure output
tmux kill-session -t ostium_24h   # aturar
```

---

## 11. Resultats Recents (Referència)

| Símbol | Candles | Corr | Dir agree | Veredicte |
|--------|---------|------|-----------|-----------|
| EURUSD | 1414    | 0,95 | 88,5%     | PARTIAL   |
| XAUUSD | 1340    | 0,43 | 92,2%     | FAIL      |

EURUSD: corr bona; dir_agree <95% → PARTIAL. XAUUSD: possible desajust instrument/offset.

---

**Última actualització:** 2026-02-18
