# Gold Parity Suite (T8.49)

Marc estable per validar paritat LAB vs MT4/SQ amb oracle certificat.

## Què és

Gold Suite és el procés canònic per certificar que el nostre motor de candles, indicadors i execució coincideixen amb MT4/SQ. L’ordre és: **candles → indicador → signal → execució → trades**.

## Regles

- **No network:** Oracle CSV local, sense API
- **No synthetic:** Dades reals SQ export
- **Oracle-first:** Primer certificar candles, després la resta
- **No-delete:** No esborrar artifacts; arxivar si cal

## Com obtenir oracle SQ

```bash
# Cal aturar sqcli-docker abans
docker compose -f <sqcli-compose> stop sqcli

docker compose -f <sqcli-compose> run --rm sqcli sqcli -data action=export \
  symbols=EURUSD_M1_dukas_M1_UTCMinus05 timeframe=M1 \
  datefrom=2026.01.20 dateto=2026.02.03 \
  outputdir=/home/squser/SQ/user/t842_oracle_export

docker compose -f <sqcli-compose> start sqcli
```

CSV resultant: `user/t842_oracle_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv`

## Com executar

### Smoke curt (2 dies)

```bash
python3 lab/gold/runner.py run \
  --case rsi35_exit60_m1_oracle \
  --oracle-csv "/mnt/volume-SQ/user/t842_oracle_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv" \
  --eval-from 2026-02-01 --eval-to 2026-02-03 \
  --eval-to-ts 1770089460 \
  --outdir lab/gold/artifacts
```

### Via Docker

```bash
./scripts/run_t849_gold_smoke.sh [--docker]
```

## Artifacts

Sota `lab/gold/artifacts/<case>/EURUSD/1m/<range>/`:

| Fitxer | Descripció |
|--------|------------|
| oracle_report.json | Rows, checksum, estat |
| gap_report.json | Gaps dins eval |
| indicator_report.json | RSI config |
| signal_events.csv | ts on signal=true |
| trades.csv | Lab trades |
| parity_report.json | state, matched, pass |

## Com afegir un indicador nou

1. Crear `indicators/<name>.py` + `indicators/spec_<name>.md`
2. Implementar o importar des de parity
3. Afegir case a `cases/` o ampliar un existent
4. Actualitzar `gold_registry.yaml`

## Com escalar

- **6m → 1y → 5y:** Export oracle amb rang ampliat, rerun gold
- **H1:** Oracle SQ H1 o agregat M1→H1 (T8.51)

## Referències

- Harness legacy: `lab/runner/out_compare/mt4_m1_rsi35_exit60_parity.py`
- State machine: `lab/gold/state_machine.md`
- ESTAT: `docs/ESTAT.md` T8.49
