# scripts/oneshot/ — Scripts puntuals (no operatius)

**Propòsit:** Scripts utilitzats per tasques puntuals (backfill, migració, validació LAB, diagnosi). No formen part del flux operatiu oficial.

**Criteri:** Scripts classificats com `ONESHOT` al triage (`docs/scripts_cleanup_triage.md`). Tenen valor com a referència, precedent o diagnosi, però no són recurrents.

**No s'han de considerar part del flux oficial.** Per scripts operatius, veure l'arrel de `scripts/`.

---

## Dependències rellevants

| Script | Relació |
|-------|---------|
| `run_t830_contract_grid.sh` | Precedent per `run_t831_trade_diff.sh` i `run_t833_time_alignment_sweep.sh` |
| `run_t831_trade_diff.sh` | Precedent per `run_t836_signal_def_sweep.sh` |
| `run_t833_time_alignment_sweep.sh` | Relacionat amb el grid de `run_t830` |
| `run_t915_gate_parity.sh` | Wrapper antic; substituït funcionalment per `scripts/run_t915_sq_bs_m1_parity_gate.sh` |

**Ordre típic per pipeline LAB:** t830 → t831 → t832 → t833 → t836

---

## Referències

- `docs/scripts_cleanup_triage.md` — triage i classificació
- `docs/ESTAT.md` — tasques T8.xx amb comandes de verificació
