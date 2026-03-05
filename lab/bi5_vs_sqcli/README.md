# lab/bi5_vs_sqcli — BI5 5 anys directe vs SQCLI

1. **Baixada directa BI5:** 5 anys de M1 BID des de Dukascopy (URL `.bi5`) i desats a `artifacts/bi5_5y.csv`.
2. **Comparació:** mateix rang amb l’export SQCLI (EURUSD M1 UTCMinus05); barra a barra (ts, OHLC).
3. **Resultat:** `artifacts/summary.json` (PASS/FAIL, mismatches, missing_in_bi5, extra_in_bi5).

## Ús

Export SQCLI (un cop, mateix rang 5 anys):

```bash
# Dins el contenidor/entorn sqcli, export 2019-01-01 → 2024-01-01
# symbols=EURUSD_M1_dukas_M1_UTCMinus05 timeframe=M1 datefrom=2019-01-01 dateto=2024-01-01
```

Executar (des del project root BrokerageService):

```bash
# Baixa BI5 5y (2019→2024) i compara amb el CSV SQCLI
python3 -m lab.bi5_vs_sqcli.run_bi5_sqcli_parity --sq-csv /path/to/EURUSD_M1_dukas_M1_UTCMinus05-M1-No\ Session.csv
```

Només comparar (sense tornar a baixar BI5):

```bash
python3 -m lab.bi5_vs_sqcli.run_bi5_sqcli_parity --compare-only --sq-csv /path/to/export.csv
```

Rang i sortida:

```bash
python3 -m lab.bi5_vs_sqcli.run_bi5_sqcli_parity --sq-csv /path/to/export.csv --from 2020-01-01 --to 2025-01-01 --out-dir ./lab/bi5_vs_sqcli/artifacts
```

La baixada BI5 pot trigar (rate limit 0.1s per dia → ~3 min per any). El resultat es desa a `out_dir/summary.json`.
