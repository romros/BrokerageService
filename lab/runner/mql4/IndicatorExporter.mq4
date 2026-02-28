//+------------------------------------------------------------------+
//|  IndicatorExporter.mq4  — T8.21 Indicator Parity Harness        |
//|                                                                  |
//|  Exporta iMA(200), iRSI(14), iATR(14) barra-a-barra per D1      |
//|  Output: MQL4/Files/indicators_mt4_<FROM>_<TO>.csv              |
//|                                                                  |
//|  Ús:                                                             |
//|   1. Copiar a MT4/MQL4/Experts/                                  |
//|   2. Configurar FROM_DATE, TO_DATE, SYMBOL als inputs            |
//|   3. Attach a qualsevol chart (no importa el TF — llegeix D1)   |
//|   4. El CSV es genera a MQL4/Files/                              |
//|                                                                  |
//|  Format output CSV:                                              |
//|   ts_utcm5,date_utcm5,open,high,low,close,                      |
//|   ema200_mt4,rsi14_mt4,atr14_mt4,signal_mt4                     |
//|                                                                  |
//|  Nota: les dates del CSV son UTC-5 (Dukascopy UTCMinus05).       |
//|  compare_indicators.py converteix automàticament (+5h = UTC).   |
//+------------------------------------------------------------------+

#property strict
#property script_show_inputs

//--- Inputs
input string   SYMBOL       = "EURUSD";          // Símbol
input string   FROM_DATE    = "2012.01.01";       // Data inici (YYYY.MM.DD)
input string   TO_DATE      = "2014.01.01";       // Data fi    (YYYY.MM.DD)
input int      EMA_PERIOD   = 200;                // Període EMA
input int      RSI_PERIOD   = 14;                 // Període RSI
input int      ATR_PERIOD   = 14;                 // Període ATR
input double   RSI_ENTRY    = 35.0;               // Threshold RSI entrada
input string   FILENAME     = "";                 // Nom fitxer (buit = auto)

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   ExportIndicators();
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Export function                                                   |
//+------------------------------------------------------------------+
void ExportIndicators()
{
   datetime from_dt = StringToTime(FROM_DATE);
   datetime to_dt   = StringToTime(TO_DATE);

   // Determina nom fitxer
   string fname = FILENAME;
   if(fname == "")
   {
      // Auto-name: indicators_mt4_YYYYMMDD_YYYYMMDD.csv
      string f_str = StringSubstr(FROM_DATE, 0, 4) + StringSubstr(FROM_DATE, 5, 2) + StringSubstr(FROM_DATE, 8, 2);
      string t_str = StringSubstr(TO_DATE,   0, 4) + StringSubstr(TO_DATE,   5, 2) + StringSubstr(TO_DATE,   8, 2);
      fname = "indicators_mt4_" + f_str + "_" + t_str + ".csv";
   }

   int fh = FileOpen(fname, FILE_WRITE | FILE_CSV, ",");
   if(fh == INVALID_HANDLE)
   {
      Print("ERROR: no s'ha pogut crear el fitxer: ", fname);
      return;
   }

   // Header
   FileWrite(fh, "ts_utcm5", "date_utcm5",
             "open", "high", "low", "close",
             "ema200_mt4", "rsi14_mt4", "atr14_mt4", "signal_mt4");

   // Iterem per barres D1 (d'antiga a nova)
   // iBarShift retorna l'índex de la barra per la data donada
   // La barra 0 és la més recent, N-1 la més antiga

   int total_bars = iBars(SYMBOL, PERIOD_D1);
   int rows_written = 0;

   for(int shift = total_bars - 1; shift >= 0; shift--)
   {
      datetime bar_time = iTime(SYMBOL, PERIOD_D1, shift);

      // Filtra per rang [from_dt, to_dt)
      if(bar_time < from_dt) continue;
      if(bar_time >= to_dt)  continue;

      // OHLCV
      double o = iOpen (SYMBOL, PERIOD_D1, shift);
      double h = iHigh (SYMBOL, PERIOD_D1, shift);
      double l = iLow  (SYMBOL, PERIOD_D1, shift);
      double c = iClose(SYMBOL, PERIOD_D1, shift);

      // Indicadors MT4 natius
      double ema200 = iMA  (SYMBOL, PERIOD_D1, EMA_PERIOD, 0, MODE_EMA, PRICE_CLOSE, shift);
      double rsi14  = iRSI (SYMBOL, PERIOD_D1, RSI_PERIOD, PRICE_CLOSE, shift);
      double atr14  = iATR (SYMBOL, PERIOD_D1, ATR_PERIOD, shift);

      // Senyal: Close[shift+1] > EMA[shift+1] AND RSI[shift+1] < RSI_ENTRY
      // (equivalent a generate_signals: prev_close > prev_ema AND prev_rsi < threshold)
      double prev_close = iClose(SYMBOL, PERIOD_D1, shift + 1);
      double prev_ema   = iMA(SYMBOL, PERIOD_D1, EMA_PERIOD, 0, MODE_EMA, PRICE_CLOSE, shift + 1);
      double prev_rsi   = iRSI(SYMBOL, PERIOD_D1, RSI_PERIOD, PRICE_CLOSE, shift + 1);
      int    signal_mt4 = (prev_close > prev_ema && prev_rsi < RSI_ENTRY) ? 1 : 0;

      // Timestamp: epoch UTC-5 (Dukascopy)
      // bar_time és la hora local del servidor MT4 (UTC-5 en aquest cas)
      long ts_utcm5 = (long)bar_time;

      // Format data: "YYYY-MM-DD HH:MM:SS"
      string date_str = TimeToString(bar_time, TIME_DATE | TIME_SECONDS);

      // Escriu fila
      FileWrite(fh,
                IntegerToString(ts_utcm5),
                date_str,
                DoubleToString(o, 6),
                DoubleToString(h, 6),
                DoubleToString(l, 6),
                DoubleToString(c, 6),
                DoubleToString(ema200, 6),
                DoubleToString(rsi14, 6),
                DoubleToString(atr14, 6),
                IntegerToString(signal_mt4));

      rows_written++;
   }

   FileClose(fh);
   Print("IndicatorExporter: done. rows=", rows_written, " → ", fname);
   Alert("IndicatorExporter done: " + IntegerToString(rows_written) + " rows → " + fname);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason) {}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick() {}
