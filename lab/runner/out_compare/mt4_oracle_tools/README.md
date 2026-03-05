# MT4 Oracle Tools — T8.40

Eines per exportar candles M1 i RSI des de MT4/SQ per paritat LAB.

## OracleExporterM1.mq4

Exporta candles M1 + RSI(14, PRICE_CLOSE) per bar.

### Instal·lació

1. Copiar `OracleExporterM1.mq4` a `MT4/MQL4/Scripts/` (o Experts/)
2. Compilar (F7) a MetaEditor
3. Obrir chart amb símbol `EURUSD_M1_dukas_M1_UTCMinus05`
4. Arrossegar el script al chart

### Output

- `candles_EURUSD_M1_UTCMinus05_20260201_20260203.csv` → MQL4/Files/
- `rsi_EURUSD_M1_UTCMinus05_20260201_20260203.csv` → MQL4/Files/

### Copiar a mt4_oracle

```bash
# Després d'executar a MT4, copiar des de MQL4/Files/ a:
cp /path/to/MQL4/Files/candles_EURUSD_M1_UTCMinus05_20260201_20260203.csv \
   lab/runner/out_compare/mt4_oracle/candles_EURUSD_M1_UTCMinus05_20260201_20260202.csv

cp /path/to/MQL4/Files/rsi_EURUSD_M1_UTCMinus05_20260201_20260203.csv \
   lab/runner/out_compare/mt4_oracle/rsi_EURUSD_M1_UTCMinus05_20260201_20260202.csv
```

**Nota:** El harness espera `*_20260201_20260202.csv` (rang inclusiu 02). Els fitxers MQL4 tenen TO exclusiu 03; renombrar o fer symlink.
