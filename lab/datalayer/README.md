# lab/datalayer — Gate 5 anys M1 BID (BS.T9.03)

Comparació **read-only** month-by-month: candles M1 de BrokerageService vs export SQCLI (EURUSD Dukascopy UTCMinus05).

**Primer pas (per defecte):** el gate obté la cobertura BS (`GET /data/coverage/EURUSD`) i tria un bloc de **5 anys (60 mesos)** consecutius amb tots els mesos `done` i `rows > 0`. Així el rang és sempre un on BS té dades BI/Parquet completes. Per forçar un rang manual: `--no-auto-range --from YYYY-MM-DD --to YYYY-MM-DD`.

## Preparar input SQ (manual)

Export candles M1 des de StrategyQuant via sqcli (cal aturar sqcli-docker abans):

```bash
docker compose -f <sqcli-compose> stop sqcli

docker compose -f <sqcli-compose> run --rm sqcli /home/squser/SQ/sqcli -data action=export \
  symbols=EURUSD_M1_dukas_M1_UTCMinus05 timeframe=M1 \
  datefrom=2020-01-01 dateto=2025-01-01 \
  outputdir=/home/squser/SQ/user/t903_5y_export

docker compose -f <sqcli-compose> start sqcli
```

CSV resultant (ex.): `EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv` dins `outputdir`.  
Requisit: tenir el fitxer accessible (p.ex. `/mnt/volume-SQ/user/t903_5y_export/...`).

## Executar el gate

```bash
# Dry-run (només llista mesos i paths)
./scripts/oneshot/run_t903_bs_sq_m1_gate.sh --dry-run

# Aplicar (1 mes per smoke)
./scripts/oneshot/run_t903_bs_sq_m1_gate.sh --apply --months 1

# 5 anys complets
./scripts/oneshot/run_t903_bs_sq_m1_gate.sh --apply
```

Directe amb Python (rang 5y descobert des de BS per defecte):

```bash
python3 -m lab.datalayer.bs_sq_m1_parity_gate \
  --sq-csv /mnt/volume-SQ/user/t903_5y_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No\ Session.csv \
  --base-url http://localhost:8081 \
  [--dry-run] [--months 1]
```

Rang manual (sense cridar cobertura BS): `--no-auto-range --from 2020-01-01 --to 2025-01-01`

## Artifacts

Sota `lab/datalayer/artifacts/BS.T9.03/`:

| Fitxer | Descripció |
|--------|-------------|
| `gate_summary.json` | PASS/FAIL, total mismatches, missing_in_bs, extra_in_bs, resum per mes |
| `gate_summary.csv` | Una fila per mes (sq_rows, bs_rows, matched_rows, mismatches, pass_preu) |
| `month=YYYY-MM/month_summary.json` | Detall del mes |
| `month=YYYY-MM/mismatches_top.csv` | Mostres de mismatches (ts, col, sq, bs, delta_pips) |
| `run.log` | Log del script (quan s’executa via run_t903) |

## Criteri PASS

- **PASS:** cap mismatch en timestamps comuns (`mismatches_on_common_ts == 0`).
- **FAIL:** qualsevol mes amb delta OHLC > 1e-5 en ts comuns.
- `missing_in_bs` / `extra_in_bs` es reporten per diagnòstic (ex. caps de setmana); no fan FAIL per si sols.

## Verificació

- BS ha d’estar en marxa (gateway :8081) i Parquet EURUSD M1 disponible per el rang.
- Comanda: `./scripts/oneshot/run_t903_bs_sq_m1_gate.sh --apply`; revisar `gate_summary.json` i `gate_summary.csv`.
