```
╔═══════════════════════════════════════════════════════════════════════════╗
║                   OSTIUM PRICE MONITORING — RESUM                         ║
║                         Data: 2026-02-17                                  ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────┐
│ 🏃 COLLECTOR EN MARXA (continu)                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Assets:    🇪🇺 EURUSD    🥇 XAUUSD    🇬🇧 GBPJPY                       │
│  Interval:  2 segons per asset (1.5 req/s total)                        │
│  Timezone:  NY time (ET, UTC-5)                                         │
│  Mode:      Indefinit (append a continuous/)                           │
│                                                                          │
│  Tmux:      ostium_24h                                                  │
│  Output:    lab/out/ostium_prices/continuous/                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 📊 PROGRÉS ACTUAL                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  EURUSD:  ▓░░░░░░░░░░░░░░░░░░░  ~10 / 1440 candles (0.6%)             │
│  XAUUSD:  ▓░░░░░░░░░░░░░░░░░░░  ~10 / 1440 candles (0.6%)             │
│  GBPJPY:  ▓░░░░░░░░░░░░░░░░░░░  ~10 / 1440 candles (0.6%)             │
│                                                                          │
│  Status:  ✅ OK (0 gaps, 0 duplicats)                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 📅 TIMELINE ANÀLISI                                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  AVUI (2026-02-17)                                                      │
│  ├─ 08:02 UTC  ✅ Captura iniciada                                      │
│  └─ ...        🏃 Capturant preus cada 2s                               │
│                                                                          │
│  DEMÀ (2026-02-18)                                                      │
│  ├─ 08:02 UTC  ✅ Captura finalitza                                     │
│  ├─ 08:00-10:00 UTC  → Executar probes qualitat Ostium                 │
│  ├─ 12:00 UTC  ✅ Dades Dukascopy disponibles (delay ~4h)               │
│  └─ 12:00-14:00 UTC  → Executar compat Ostium vs Dukascopy             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 🔍 COMANDES ÚTILS                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Check progrés:                                                         │
│  $ ./lab/ostium/scripts/check_24h_progress.sh                          │
│                                                                          │
│  Veure live:                                                            │
│  $ tmux attach -t ostium_24h                                            │
│  (Ctrl+B després D per sortir)                                          │
│                                                                          │
│  Aturar:                                                                │
│  $ tmux kill-session -t ostium_24h                                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 📚 DOCUMENTACIÓ CREADA                                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Scripts:                                                               │
│  ✅ rest_price_collector.py      (captura preus REST)                   │
│  ✅ rest_price_probe.py           (validació qualitat)                  │
│  ✅ ostium_vs_dukascopy_compat.py (comparació fonts)                    │
│  ✅ check_24h_progress.sh         (check ràpid)                         │
│  ✅ run_full_analysis.sh          (anàlisi complet demà)                │
│                                                                          │
│  Docs:                                                                  │
│  📄 docs/LAB_OSTIUM_PRICE_MONITORING.md  (investigació tècnica)         │
│  📄 lab/ostium/COMANDES_DEMA.md          (comandes per demà)            │
│  📄 lab/ostium/README.md                 (overview actualitzat)         │
│  📄 lab/out/ostium_prices/README_FINAL.md    (guia completa)            │
│  📄 lab/out/ostium_prices/TIMELINE_COMPAT.md (timeline detallada)       │
│  📄 lab/out/ostium_prices/CHECKLIST_DEMA.txt (checklist executar)       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 💡 PER QUÈ DUKASCOPY DELAY?                                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Dukascopy NO publica dades en temps real.                              │
│  Tenen ~1-4 hores de delay per forex majors.                            │
│                                                                          │
│  Exemple:                                                               │
│  • Ara (17/02 08:00 UTC): Dukascopy només té fins ~04:00 UTC           │
│  • Demà (18/02 08:00):    Dukascopy només té fins ~04:00 UTC           │
│  • Demà (18/02 12:00):    Dukascopy JA TÉ tot el rang 08:02→08:02 ✅   │
│                                                                          │
│  Per això has d'esperar fins migdia per comparar!                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 📈 EXEMPLE DADES CAPTURADES                                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  EURUSD: {"ts": 1771315860, "o": 1.18314, "h": 1.18316,                │
│           "l": 1.18304, "c": 1.18315, "v": 0}                           │
│                                                                          │
│  XAUUSD: {"ts": 1771315860, "o": 4923.09, "h": 4923.09,                │
│           "l": 4921.81, "c": 4922.75, "v": 0}                           │
│                                                                          │
│  GBPJPY: {"ts": 1771315860, "o": 1.35729, "h": 1.35742,                │
│           "l": 1.35709, "c": 1.35742, "v": 0}                           │
│                                                                          │
│  Format: ts=epoch UTC, o/h/l/c=preus, v=0 (N/A per polling)            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

╔═══════════════════════════════════════════════════════════════════════════╗
║                           TOT LLEST! 🎯                                   ║
╚═══════════════════════════════════════════════════════════════════════════╝

  El collector seguirà indefinidament (append a continuous/).
  Executa les comandes de COMANDES_DEMA.md quan calgui.
  
  Check progrés quan vulguis: ./lab/ostium/scripts/check_24h_progress.sh

```
