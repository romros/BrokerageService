# LAB Compose — Monitors supervisats

Monitors LAB s’executen via `scripts/run_lab.sh <monitor> <action>` i viuen sota `deploy/compose/lab/`.

## Ostium monitor

**Fitxer:** `ostium-monitor.yml`

**Servei:** `ostium-monitor` — polling REST Ostium, construeix candles 1m, escriu a `lab/out/ostium_prices/`.

**Comandes:**
```bash
./scripts/run_lab.sh ostium-monitor start
./scripts/run_lab.sh ostium-monitor stop
./scripts/run_lab.sh ostium-monitor status
./scripts/run_lab.sh ostium-monitor logs
```

**Config (env):**
- `OSTIUM_POLL_INTERVAL_S` (default: 2)
- `OSTIUM_LAB_SYMBOLS` (default: EURUSD,XAUUSD,GBPJPY)
- `OSTIUM_LAB_RETENTION_DAYS` (default: 14)

**Output:**
- `lab/out/ostium_prices/continuous/` — stream continu
- `lab/out/ostium_prices/daily/YYYYMMDD/` — rotació diària
- `lab/out/ostium_prices/daily/LATEST_RUN.txt` — pointer al dia actual
