# DATA PARITY GATES — BrokerageService Historical Data

**Data:** 2026-02-28
**Principi:** No es passa al gate següent si l'anterior no és PASS o PARTIAL-acceptat.

---

## Resum de gates

| Gate | Descripció | Estat | Data |
|------|-----------|-------|------|
| **Gate A** | Dukascopy M1 parity vs SQ (EURUSD) | **PARTIAL** | 2026-02-28 |
| **Gate B** | Aggregation parity M1→H1/H4/D1 | **PASS (T8.18)** | 2026-02-28 |
| **Gate C** | Dukascopy↔Ostium candle compatibility | **PASS recheck (T8.18)** | 2026-02-28 |
| **Gate D** | Runner backtest parity + paper/live | PASS (T8.11) | 2026-02-28 |

---

## Gate A: Dukascopy M1 parity vs SQ (EURUSD)

**Estat: PARTIAL (acceptat)**

### SQ baseline
- Dataset: `EURUSD_M1_dukas_M1_UTCMinus05`
- Total records: **8,499,508**
- Coverage: 2003-05-05 → 2026-02-28

### Nostra cobertura (2026-02-28)
- Total rows: **5,756,530**
- Coverage: **2007-01 → 2026-02** (175 mesos)
- Delta vs SQ: **-32.3%** (2,742,978 rows menys)

### Diagnòstic Fase A (2026-02-28)

Sync test `2003-05 → 2006-12` amb `QUALITY_MODE=ingest`:
- Resultat: `done=1, empty=43, failed=0`
- La "1 done" (2006-12) contenia 1 sola candle amb timestamp **2007-01-01 00:00 UTC** (artefacte off-by-one de rang mensual). Eliminat.
- Earliest candle real: `ts=1167609600` = **2007-01-01 00:00:00 UTC**

**Conclusió:** La Dukascopy M1 pública per EURUSD comença el **2007-01-01**. No hi ha dades M1 anteriors via API pública. SQ disposa de 2003-2006 probablement via:
- Agregació de ticks (diferent qualitat)
- Font alternativa (no pública)

### Per què PARTIAL és acceptable

1. **No-delete policy activa** (T8.16): mai s'eliminen dades per baix threshold
2. **QUALITY_MODE=ingest**: baixem tot el que Dukascopy retorna
3. La diferència (32%) reflecteix una limitació de la font, no un error de baixada
4. Per a backtesting des de 2007 (rang disponible), la paritat és verificable

### Criteris per a PASS complet

- `coverage_from <= 2003-05-05` i `total_rows >= 8,000,000`
- Requereix: font alternativa de ticks 2003-2006 + agregació M1

### Mesos missing (2007-2011, confirmats buits Dukascopy)

Els 55 mesos `2007-06 → 2011-12` estan confirmats com a buits per l'API Dukascopy. No es reintentar.

**Report complet:** `lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json`

---

## Gate B: Aggregation parity M1→H1/H4/D1

**Estat: PASS (T8.18)**

### Implementació

`application/tools/aggregation_report.py` — replica exacta de `aggregate_to_tf()` del runner LAB.

Paràmetres canònics:
- `day_offset_h=5` → boundary D1 a **05:00 UTC** (= 00:00 UTC-5, MT4/Dukascopy)
- Validació: OHLC invariants (H>=max(O,C), L<=min(O,C)), gap count, flat ratio

### Resultats (2026-02-28)

**EURUSD rang 2007-01→2008-01** (rang amb gaps Dukascopy — test robustesa):
| TF | Bars | Coverage | Invariants | Flat | Gaps |
|----|------|----------|-----------|------|------|
| 1h | 2,524 | 40.3% | OK | 0.00% | 23 |
| 4h | 654 | 41.8% | OK | 0.00% | 21 |
| 1d | 124 | 47.7% | OK | 0.00% | 21 |

Coverage baixa perquè 2007-06→2011-12 confirmats buits. Invariants OK, gaps = weekends + mesos buits normals.

**EURUSD rang 2020-01→2021-01** (rang amb dades completes, expected corregit T8.19):
| TF | Bars | Coverage | Invariants | Flat | Gaps |
|----|------|----------|-----------|------|------|
| 1h | 6,250 | 97.0% | OK | 0.00% | 52 |
| 4h | 1,581 | 98.1% | OK | 0.00% | 52 |
| 1d | 314 | 99.7% | OK | 0.00% | 52 |

52 gaps = weekends (normal FX). Coverage 97-100% confirma integritat M1 post-2012.
Nota T8.19: expected calculat exactament via calendari FX (exclou dissabte + diumenge<21h UTC).
Coverage <100% reflecteix holidays Dukascopy i buits interns de sessió (esperats).

### Conclusió

- **OHLC invariants: 100% OK** (0 barres trencades en cap rang)
- **Flat ratio: 0.00%** (cap barra sense moviment)
- **Boundary D1: 05:00 UTC** confirmat (barres D1 comencen a 2006-12-31T05:00Z + 2007-01-01T05:00Z...)
- **Gaps:** tots explicables (weekends + mesos Dukascopy buits)

**Artifacts:** `lab/out/artifacts/aggregation/EURUSD_*_aggregation_report.json`

---

## Gate C: Dukascopy↔Ostium candle compatibility

**Estat: PASS recheck (T8.18)**

### Recheck 2026-02-28

Executat `./scripts/run_compat.sh ostium` per ambdós símbols:

| Símbol | corr | dir_agree_filtered | aligned_ratio | Veredicte |
|--------|------|-------------------|---------------|-----------|
| EURUSD | 0.956 | 99.0% | 0.9957 | **PASS_BACKTEST** |
| XAUUSD | 0.959 | 96.9% | 0.9957 | **PASS_BACKTEST** |

### Historial

| Data | EURUSD corr | XAUUSD corr | Tasca |
|------|------------|------------|-------|
| T8.9 (anterior) | 0.968 | 0.977 | Primera execució |
| T8.18 recheck | 0.956 | 0.959 | Recheck post-T8.16 |

Lleugera variació (±0.01 corr) normal per finestra rolling de 24h diferent.

---

## Gate D: Runner backtest parity + paper/live

**Estat: PASS recheck (T8.19)**

### Recheck 2026-02-28 (post-Gate B)

Backtest `eurusd_ema200_rsi35_atr_d1` reexecutat amb dades estabilitzades (T8.16-T8.18):

| Mètrica | T8.11 | T8.19 recheck | Canvi |
|---------|-------|--------------|-------|
| n_trades | 18 | 18 | = |
| net_pnl | 1.96% | 1.96% | = |
| win_rate | 44.44% | 44.44% | = |
| max_dd | 4.39% | 4.39% | = |
| entry_match_rate vs MT4 | 50.0% | 50.0% | = |

**Conclusió:** Resultats estables — les millores de qualitat de dades (T8.13-T8.18) no han alterat el comportament del backtest. Entry match-rate 50% és el límit assolit amb ATR Wilder + warmup + D1 offset (T8.11). La diferència residual LAB↔MT4 és per model tick intrabar diferent (no resoluble sense ticks).

**Report:** `lab/runner/out_compare/report_after_gate_b.json`

### Intrabar sensitivity analysis (T8.20)

Implementats 3 modes `--intrabar-mode {sl_first,tp_first,heuristic}` a `run_backtest.py`.

| Mode | n_trades | net_pnl | win_rate | max_dd | entry_match_rate vs MT4 |
|------|----------|---------|---------|--------|------------------------|
| sl_first | 18 | 1.96% | 44.44% | 4.39% | **50.0%** |
| tp_first | 18 | 1.96% | 44.44% | 4.39% | **50.0%** |
| heuristic | 18 | 1.96% | 44.44% | 4.39% | **50.0%** |

**Conclusió T8.20:** Cap barra D1 tocava simultàniament SL i TP (`dual_hit_bars=0`). Els 3 modes produeixen trades **idèntics**. La divergència LAB↔MT4 (4 trades missing, 50% entry match) **no és per tick order intrabar**. Causa residual: diferència de model de senyals EMA/RSI/ATR entre LAB Python i MT4 MQL4.

**Recomanació:** `no_ticks_needed_for_d1_parity` — no cal implementar tick replay per millorar la paritat D1.

**Report:** `lab/runner/out_compare/intrabar_sensitivity_report.json`

---

## Política de qualitat de dades

### QUALITY_MODE

| Mode | Quan usar | Comportament |
|------|-----------|-------------|
| `ingest` (default) | Sempre en producció/sync | Accepta qualsevol rows>0. Mai falla per cobertura baixa. |
| `integrity` | Diagnòstic manual post-sync | Aplica MIN_ROWS/MIN_COMPLETENESS/MAX_FLAT_RATIO. |

### No-delete policy (T8.16)

`sync_manager._process_month()` **mai fa `unlink()`** sobre parquets amb rows>0.
L'única eliminació possible és via `repair_empty_parquets.py --fix` (explícit, manual).

### Thresholds (mode integrity)

| Variable | Default | Descripció |
|----------|---------|-----------|
| `MIN_ROWS_MONTH_1M` | 10,000 | Mínim rows per mes M1 |
| `MAX_FLAT_RATIO_GATE` | 0.05 | Màxim ratio barres O=H=L=C |
| `MIN_COMPLETENESS_1M` | 0.50 | Mínim completeness (rows/expected_minutes) |

### Camps observabilitat (SyncJob)

- `done`: mesos escrits correctament
- `empty`: mesos confirmats buits per Dukascopy (retorna [])
- `suspect`: mesos escrits però amb cobertura baixa (informatiu)
- `failed`: mesos que han fallat després de tots els retries

---

## Historial de canvis

| Data | Tasca | Canvi |
|------|-------|-------|
| 2026-02-28 | T8.20 | Intrabar modes (sl_first/tp_first/heuristic) — 3 modes idèntics, no_ticks_needed |
| 2026-02-28 | T8.19 | Fix expected_bar_count (<=100%), Gate D recheck PASS, compare_trades after_gate_b |
| 2026-02-28 | T8.18 | Gate B PASS (aggregation M1→H1/H4/D1) + Gate C recheck PASS |
| 2026-02-28 | T8.17 | Gate A PARTIAL: Dukascopy EURUSD M1 comença 2007-01 |
| 2026-02-28 | T8.16 | QUALITY_MODE ingest/integrity + no-delete + empty/suspect counters |
| 2026-02-28 | T8.14 | Quality gate mensual al sync |
| 2026-02-28 | T8.13 | Fix parquets buits perpetus |
| 2026-02-28 | T8.12 | Parity checker + report EURUSD M1 |
