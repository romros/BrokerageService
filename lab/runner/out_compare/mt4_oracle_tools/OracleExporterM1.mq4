//+------------------------------------------------------------------+
//|  OracleExporterM1.mq4  — T8.40 MT4 Oracle Export (candles M1)   |
//|                                                                  |
//|  Exporta candles M1 + RSI(14, PRICE_CLOSE) per bar.              |
//|  Output: MQL4/Files/ → copiar a lab/.../mt4_oracle/              |
//|                                                                  |
//|  Ús:                                                             |
//|   1. Copiar a MT4/MQL4/Experts/ (o Scripts/)                     |
//|   2. Símbol = EURUSD_M1_dukas_M1_UTCMinus05 (o el que tingui SQ) |
//|   3. FROM_DATE, TO_DATE = rang 2026.02.01 → 2026.02.03            |
//|   4. Executar (drag to chart)                                    |
//|   5. CSV a MQL4/Files/ → copiar a mt4_oracle/                    |
//|                                                                  |
//|  Format candles: ts, dt_utcminus05, open, high, low, close        |
//|  Format RSI:     ts, rsi14_close                                 |
//|  ts = epoch UTC (MT4 bar_time és UTC per Dukascopy)              |
//+------------------------------------------------------------------+

#property strict
#property script_show_inputs

//--- Inputs
input string   SYMBOL       = "EURUSD_M1_dukas_M1_UTCMinus05";  // Símbol MT4/SQ
input string   FROM_DATE    = "2026.02.01";                     // Data inici (YYYY.MM.DD)
input string   TO_DATE      = "2026.02.03";                     // Data fi (exclusiu)
input int      RSI_PERIOD   = 14;                               // RSI període
input string   CANDLES_FILE = "";                               // Buit = auto
input string   RSI_FILE     = "";                               // Buit = auto

//+------------------------------------------------------------------+
//| Script start function                                             |
//+------------------------------------------------------------------+
void OnStart()
{
   ExportCandles();
   ExportRSI();
}

//+------------------------------------------------------------------+
//| Export candles M1                                                 |
//+------------------------------------------------------------------+
void ExportCandles()
{
   datetime from_dt = StringToTime(FROM_DATE);
   datetime to_dt   = StringToTime(TO_DATE);

   string fname = CANDLES_FILE;
   if(fname == "")
   {
      string f_str = StringSubstr(FROM_DATE, 0, 4) + StringSubstr(FROM_DATE, 5, 2) + StringSubstr(FROM_DATE, 8, 2);
      string t_str = StringSubstr(TO_DATE,   0, 4) + StringSubstr(TO_DATE,   5, 2) + StringSubstr(TO_DATE,   8, 2);
      fname = "candles_EURUSD_M1_UTCMinus05_" + f_str + "_" + t_str + ".csv";
   }

   int fh = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ",");
   if(fh == INVALID_HANDLE)
   {
      Print("ERROR candles: no s'ha pogut crear ", fname);
      return;
   }

   FileWrite(fh, "ts", "dt_utcminus05", "open", "high", "low", "close");

   int total_bars = iBars(SYMBOL, PERIOD_M1);
   int rows = 0;

   for(int shift = total_bars - 1; shift >= 0; shift--)
   {
      datetime bar_time = iTime(SYMBOL, PERIOD_M1, shift);
      if(bar_time < from_dt) continue;
      if(bar_time >= to_dt)  continue;

      double o = iOpen (SYMBOL, PERIOD_M1, shift);
      double h = iHigh (SYMBOL, PERIOD_M1, shift);
      double l = iLow  (SYMBOL, PERIOD_M1, shift);
      double c = iClose(SYMBOL, PERIOD_M1, shift);

      long ts = (long)bar_time;
      string dt_str = TimeToString(bar_time, TIME_DATE | TIME_SECONDS);

      FileWrite(fh, IntegerToString(ts), dt_str,
                DoubleToString(o, 5), DoubleToString(h, 5),
                DoubleToString(l, 5), DoubleToString(c, 5));
      rows++;
   }

   FileClose(fh);
   Print("OracleExporterM1 candles: ", rows, " rows → ", fname);
}

//+------------------------------------------------------------------+
//| Export RSI(14, PRICE_CLOSE) per bar M1                            |
//+------------------------------------------------------------------+
void ExportRSI()
{
   datetime from_dt = StringToTime(FROM_DATE);
   datetime to_dt   = StringToTime(TO_DATE);

   string fname = RSI_FILE;
   if(fname == "")
   {
      string f_str = StringSubstr(FROM_DATE, 0, 4) + StringSubstr(FROM_DATE, 5, 2) + StringSubstr(FROM_DATE, 8, 2);
      string t_str = StringSubstr(TO_DATE,   0, 4) + StringSubstr(TO_DATE,   5, 2) + StringSubstr(TO_DATE,   8, 2);
      fname = "rsi_EURUSD_M1_UTCMinus05_" + f_str + "_" + t_str + ".csv";
   }

   int fh = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ",");
   if(fh == INVALID_HANDLE)
   {
      Print("ERROR RSI: no s'ha pogut crear ", fname);
      return;
   }

   FileWrite(fh, "ts", "rsi14_close");

   int total_bars = iBars(SYMBOL, PERIOD_M1);
   int rows = 0;

   for(int shift = total_bars - 1; shift >= 0; shift--)
   {
      datetime bar_time = iTime(SYMBOL, PERIOD_M1, shift);
      if(bar_time < from_dt) continue;
      if(bar_time >= to_dt)  continue;

      double rsi = iRSI(SYMBOL, PERIOD_M1, RSI_PERIOD, PRICE_CLOSE, shift);
      long ts = (long)bar_time;

      FileWrite(fh, IntegerToString(ts), DoubleToString(rsi, 4));
      rows++;
   }

   FileClose(fh);
   Print("OracleExporterM1 RSI: ", rows, " rows → ", fname);
   Alert("OracleExporterM1 done. Candles + RSI → MQL4/Files/");
}
