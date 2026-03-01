# ExitAfterBars — Spec certificat

## Contracte

- **Entry:** On Bar Open (open[i]) quan RSI[i-1] < threshold
- **Exit:** open[i+exit_bars] (60 bars després)
- **Max posició:** 1
- **Same-bar reentry:** Si sortim a la barra i, comprovem signal a la mateixa barra i (MT4 pot exit+entry mateix bar)

## Weekend block

- Fri 22:00 UTC → Sun 22:00 UTC: no trade
