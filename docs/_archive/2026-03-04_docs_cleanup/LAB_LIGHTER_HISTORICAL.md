# LAB — Historical Candles Feasibility (Lighter)

> **T5.32 (2026-02):** Lighter LAB arxivat. Scripts ara a `_archive/lab/2026-02-legacy-purge/lighter/scripts/`. Repo Ostium-first.

**TASK:** Decidir si P4 (backfill + gap repair) és viable amb Lighter com a "primary històric", o si cal fallback (Dukascopy) més aviat.

**Script (arxivat):** `_archive/lab/2026-02-legacy-purge/lighter/scripts/fetch_historical_candles.py`

---

## Symbols amb històric 1m

| Symbol (Lighter) | Canonical | market_id (mainnet) | Històric 1m |
|------------------|-----------|---------------------|-------------|
| **EURUSD**       | EURUSD    | 96                  | ✅ Sí       |
| **XAU**          | XAUUSD    | 92                  | ✅ Sí       |
| **ETH**          | ETH       | 0 o 2048 (ETHUSDC)  | ✅ Sí (mainnet) |
| **BTC**          | BTC       | 1                   | ✅ Sí       |

**Testnet:** Històric limitat o buit; usar **mainnet** per validar.

---

## earliest_ts / latest_ts

- **Font:** CandlestickApi (SDK) — `resolution=1m`, paginació 500 candles/request
- **Rang:** `[since_ts, to_ts)` sobre starts-of-minute UTC
- **Evidència (2026-02):** EURUSD 72h → `earliest_ts=1770932580`, `latest_ts=1771191720`, 4320 candles, 9 requests

---

## Rate limits / errors comuns / retry

| Situació        | Comportament | Recomanació                    |
|----------------|--------------|--------------------------------|
| **429**        | Retry 3× amb backoff (1s, 2s, 3s) | Pausa 0.2s entre chunks |
| **400 invalid param** | `resolution` ha de ser `1m` (no `1`) | Usar enum: 1m, 5m, 15m, … |
| **Timestamps** | Lighter retorna `t` en **ms**; el script converteix a segons | Normalització automàtica |
| **Duplicats**  | Paginació pot solapar; el script deduplica per `ts` | Output sense duplicats |

**Límits API:** ~60 req/min (apidocs.lighter.xyz). Per 72h (4320 min) amb chunks de 500 → ~9 requests.

---

## Conclusió

**Viable com a primary backfill** per EURUSD i XAU (mainnet), amb les condicions següents:

1. **Mainnet obligatori** per RWA (testnet no té històric consistent)
2. **Paginator ≤500** candles/request — implementat
3. **Normalització** ts start-of-minute UTC, volume=0 si absent — implementat
4. **Validació** duplicates=0 (post-dedup), ts_step_errors=0, missing_minutes≤1 — implementat

**Cal fallback (Dukascopy)** si:
- Lighter no ofereix històric suficient per algun RWA nou
- Rate limits impedeixen backfills massius
- Es requereix històric >72h amb garanties d’integritat estrictes (Gate A compat_probe)

---

## Comandes

**Docker (recomanat, mateix entorn que prod):** Paths arxivats — muntar `_archive/lab/2026-02-legacy-purge/lighter` si cal.
```bash
# coverage_probe (path arxivat)
docker compose run --rm lighter-lab python3 _archive/lab/2026-02-legacy-purge/lighter/scripts/coverage_probe.py --symbol EURUSD --symbol XAU

# fetch_historical_candles (path arxivat)
docker compose run --rm lighter-lab python3 _archive/lab/2026-02-legacy-purge/lighter/scripts/fetch_historical_candles.py --symbol EURUSD --hours 72 --out-dir /datafiles/lab_lighter_history
```

**Host (pip):** `python3 _archive/lab/2026-02-legacy-purge/lighter/scripts/...` — requereix `pip install -r _archive/lab/2026-02-legacy-purge/lighter/requirements.txt`.

**Config:** `LIGHTER_BASE_URL` (mainnet per RWA), `LIGHTER_MARKET_ID_MAP` (opcional JSON), `.env` a `_archive/lab/2026-02-legacy-purge/lighter/` (muntat al container).

---

## coverage_probe (QA lab)

**Script (arxivat):** `_archive/lab/2026-02-legacy-purge/lighter/scripts/coverage_probe.py`

Troba `earliest_ts` i `latest_ts` 1m amb probing incremental + binary search. Valida finestra recent 72h (missing_minutes, max_gap, duplicates, ts_step_errors). Rate limit 60 req/min.

```bash
docker compose run --rm lighter-lab python3 _archive/lab/2026-02-legacy-purge/lighter/scripts/coverage_probe.py --symbol EURUSD --symbol XAU
docker compose run --rm lighter-lab python3 _archive/lab/2026-02-legacy-purge/lighter/scripts/coverage_probe.py --symbol EURUSD --skip-earliest
```

**Output:** `lab/out/coverage_mainnet_<symbol>.json`

**Invariants 72h:** `expected_minutes`, `missing_minutes==0`, `duplicates_after_dedup==0`, `ts_step_errors==0`, `candles_in_window==expected_minutes`. Mètriques: `raw_count`, `unique_count`, `duplicates_raw`.

**earliest_ts:** Binary search; si brotli decode error → fallback httpx amb `Accept-Encoding: identity`. `--skip-earliest` per omitir.

**Rate limits:** [Volume Quota](https://apidocs.lighter.xyz/docs/volume-quota-program) aplica a SendTx; candlestick API usa rate limits generals (~60 req/min). Probe: `MIN_SLEEP_BETWEEN_REQ=1.05s`, retry 429.

**Decisió:** Lighter recent viable (72h OK); Dukascopy per històric pre-Lighter.

---

## time_semantics_probe (P0.3b)

**Script (arxivat):** `_archive/lab/2026-02-legacy-purge/lighter/scripts/time_semantics_probe.py`

Demostra si les candles de Lighter venen en UTC start-of-minute o si hi ha offset. Boundary probe: `latest_ts` vs `now_floor_utc_ts - 60`.

```bash
docker compose run --rm lighter-lab python3 _archive/lab/2026-02-legacy-purge/lighter/scripts/time_semantics_probe.py --symbol EURUSD --minutes 180
```

**Output:** `lab/out/time_semantics_<symbol>.json`

**Conclusió (evidència 2026-02):** t és UTC start-of-minute. Retorna només tancades (latest = now_floor - 60). NO hi ha conversió de TZ; ts epoch UTC.

---

## Time semantics (canònic)

**Canònic (confirmat):**

* `t` és UTC start-of-minute.
* Retorna només candles tancades: `latest_ts == now_floor_utc_ts - 60`.
* NO s'aplica conversió de timezone al dataset.
* `CANONICAL_TZ=America/New_York` és només per queries/particionat/display.

**Implica (invariants):**

| Invariant | Descripció |
|-----------|------------|
| Dataset canònic | `ts` epoch UTC start-of-minute |
| Rang de query | `[since_ts, to_ts)` (to exclusiu) |
| Escrit | Mai escriure candle parcial |

**Duplicats:** `duplicates_raw` pot existir per solapament API; `duplicates_after_dedup == 0` és el que importa per dataset canònic.
