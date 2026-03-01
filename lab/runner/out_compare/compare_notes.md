# Compare notes — LAB vs SQ engines

## T8.30 Contract grid (entry_fill × signal_contract)

Exploració del contracte senyal/entrada per maximitzar entry_match_rate vs MT4 sense passes manuals.

### Contractes provats

| entry_fill | signal_contract | Descripció |
|------------|-----------------|------------|
| open_i | mt4_baropen | Senyal a barra i (usa indicadors de i-1) → entrada a open[i] (MT4 On Bar Open) |
| open_i1 | v2 | Senyal a i-1 → entrada a open[i] (comportament LAB original, 1 bar delay) |
| open_i | v2 | Mix |
| open_i1 | mt4_baropen | Mix |

### Artifacts T8.30

- `lab/runner/out_compare/contract_grid_report.json` — resultats de totes les combinacions
- `lab/runner/out_compare/best_contract.txt` — millor combinació (entry_match_rate primari, n_trades secundari)
- `lab/runner/out_compare/contract_<label>/` — backtest + report per combinació

### Target

- entry_match_rate > 60%
- n_trades proper a 22 (MT4)

Si cap combinació millora: STOP, report "oracle indicadors CSV necessari".

---

## T8.31 Trade Diff Analyzer

Diagnòstic de causes per trades unmatched (MT4 vs LAB best contract).

### Categories

| Categoria | Descripció |
|-----------|------------|
| DATA_MISSING | No hi ha candles/indicadors LAB en aquella data |
| SIGNAL_MISMATCH | Hi ha dades, signal LAB=false (MT4 sí ha entrat) |
| CONTRACT_SHIFT | Signal a barra adjacent (±k dies) |
| EXIT_CASCADE | LAB tenia signal però ja en trade (max 1 obert) |

### Artifacts

- `indicators_LAB_full.csv` — export via export_indicators_csv --mt4-like
- `trade_diff_report.json` — detall per trade
- `trade_diff_report.csv` — resum

### Execució

```bash
./scripts/run_t831_trade_diff.sh
```

---

## T8.32 Quick Parity Triage

Triage automàtic <20s per decidir tipus de divergència sense recalcular indicadors.

### Micro-checks

| # | Check | Artifact | Flag |
|---|-------|----------|------|
| 1 | Timestamp sanity (primers N MT4 entries, distribució hores) | triage_time_sanity.json | TIME_ALIGNMENT_SUSPECT |
| 2 | Local gap (finestra t±5 al divergence_bar) | triage_gap_check.json, window_around_divergence.csv | DATA_MISSING |
| 3 | Contract shift (signal_lab a t±1..t±3) | triage_shift_check.json | CONTRACT_SHIFT_LIKELY |
| 4 | RSI range plausibility (RSI/EMA/close a t i t±3) | triage_indicator_snapshot.json | INDICATOR_VARIANT_SUSPECT |

### NEXT_STEP

- `DATA_REPAIR` — gaps o fallback
- `TIME_ALIGNMENT_SWEEP` — entries no al boundary esperat (05:00 UTC)
- `RSI_VARIANT_SWEEP` — RSI lluny del llindar però crosses a prop
- `CONTRACT_SHIFT` — signal adjacent però no a t

### Execució

```bash
./scripts/run_t832_triage.sh
```

### Artifacts

`lab/runner/out_compare/artifacts/T8.32/<strategy>/<symbol>/<tf>/<from_to>/`

- triage_report.json (NEXT_STEP + flags)
- triage_time_sanity.json, triage_gap_check.json, triage_shift_check.json, triage_indicator_snapshot.json
- window_around_divergence.csv
- run.log

---

## T8.33 Time Alignment Sweep

Sweep d'offsets (hores) als timestamps MT4 per maximitzar matching MT4↔LAB i minimitzar CONTRACT_SHIFT/EXIT_CASCADE.

### Criteri best_offset

1. max matched
2. min contract_shift + exit_cascade
3. min signal_mismatch
4. tie-break: min |offset|

### Execució

```bash
./scripts/run_t833_time_alignment_sweep.sh
```

### Artifacts

`lab/runner/out_compare/artifacts/T8.33/<strategy>/<symbol>/<tf>/<from_to>/`

- time_alignment_sweep.csv
- time_alignment_report.json
- best_offset.txt
- trade_diff_report_best_offset.json + .csv (opcional)
- run.log

---

## T8.34 D1 Series Shape Audit (Sunday bar policy)

Auditoria de policies D1 per handling diumenge: baseline, drop_sunday, merge_sunday_into_monday.

### Policies

| Policy | Descripció |
|--------|------------|
| baseline | Tal qual |
| drop_sunday | Elimina barres diumenge NY |
| merge_sunday_into_monday | Fusiona OHLC diumenge dins dilluns, elimina diumenge |

### Execució

```bash
./scripts/run_t834_d1_policy_audit.sh
```

### Artifacts

`lab/runner/out_compare/artifacts/T8.34/<strategy>/<symbol>/<tf>/<from_to>/`

- d1_policy_audit.csv
- d1_policy_audit.json (NEXT_STEP, best_policy)
- first_divergence_window_<policy>.csv
- run.log

### NEXT_STEP

- `RERUN_BACKTEST_WITH_POLICY=<policy>` si hi ha millora
- `RSI_VARIANT_SWEEP` si no hi ha canvi rellevant
