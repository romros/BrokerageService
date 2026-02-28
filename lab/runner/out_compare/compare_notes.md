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
