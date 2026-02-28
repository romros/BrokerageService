"""
T8.12 — ParityChecker: mètriques de completitud M1 per mes vs target SQ.

Escaneja els parquets mensuals d'un símbol i calcula per cada mes:
- records: nombre de candles
- expected_minutes: minuts esperats (dies laborables * 1440)
- completeness_ratio: records / expected_minutes
- flat_bars: barres on O=H=L=C (dades pobres/repetides)
- flat_bars_ratio: flat_bars / records
- status: "ok" | "bad" | "missing"

Un mes és "bad" si:
  records < expected * min_records_ratio  (default 0.90)
  O flat_bars_ratio > max_flat_ratio       (default 0.02)

Un mes és "missing" si el fitxer parquet no existeix al disc.

Ús:
    checker = ParityChecker("/datafiles", "EURUSD", "1m")
    report = checker.run("2003-05-01", "2026-02-28")
    print(report.total_records, report.months_bad)
"""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MonthParity:
    year: int
    month: int
    records: int
    expected_minutes: int       # dies laborables * 1440 (excl. weekends)
    completeness_ratio: float   # records / expected_minutes (0.0 si expected=0)
    flat_bars: int              # barres on O=H=L=C
    flat_bars_ratio: float      # flat_bars / records (0.0 si records=0)
    status: str                 # "ok" | "bad" | "missing"


@dataclass
class ParityReport:
    symbol: str
    tf: str
    generated_at: str           # ISO UTC
    total_records: int
    target_records: int         # 8_499_508 per EURUSD M1
    delta_vs_target_pct: float  # (total - target) / target * 100
    coverage_from: str          # "YYYY-MM-DD" o ""
    coverage_to: str            # "YYYY-MM-DD" o ""
    months_total: int
    months_ok: int
    months_bad: List[str]       # ["2004-03", ...]
    months_missing: List[str]   # mesos en rang sense parquet
    thresholds: dict            # {"min_records_ratio": 0.90, "max_flat_ratio": 0.02}
    per_month: List[MonthParity]

    def to_dict(self) -> dict:
        d = asdict(self)
        # per_month: list de dicts
        return d


# ---------------------------------------------------------------------------
# ParityChecker
# ---------------------------------------------------------------------------

# Records per mes esperats per EURUSD (FX 5 dies/setmana, 24h/dia)
# Usar com a target_records per defecte si no es passa cap
EURUSD_TARGET_RECORDS = 8_499_508


class ParityChecker:
    """
    Analitza parquets mensuals 1m d'un símbol i genera un ParityReport.

    Paràmetres:
        datafiles_root: arrel on viuen els parquets
            (ex: "/datafiles", conté historical_parquet/{symbol}/tf=1m/...)
        symbol: ex "EURUSD"
        tf: ex "1m"
        min_records_ratio: threshold de completitud (default 0.90)
        max_flat_ratio: threshold flat bars (default 0.02)
        target_records: records totals esperats vs SQ (default 8_499_508)
    """

    def __init__(
        self,
        datafiles_root: str | Path,
        symbol: str,
        tf: str = "1m",
        min_records_ratio: float = 0.90,
        max_flat_ratio: float = 0.02,
        target_records: int = EURUSD_TARGET_RECORDS,
    ):
        self._root = Path(datafiles_root)
        self.symbol = symbol.upper()
        self.tf = tf
        self.min_records_ratio = min_records_ratio
        self.max_flat_ratio = max_flat_ratio
        self.target_records = target_records

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def run(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> ParityReport:
        """
        Analitza tots els mesos en el rang [from_date, to_date] i retorna un ParityReport.

        from_date / to_date: "YYYY-MM-DD" o None (default: primer/últim mes disponible
        o el rang complet 2003-01 → avui si no hi ha parquets).
        """
        import pandas as pd

        now_utc = datetime.now(tz=timezone.utc)

        # Determinar rang de mesos
        from_year, from_month, to_year, to_month = self._resolve_range(
            from_date, to_date
        )

        per_month: List[MonthParity] = []
        total_records = 0
        months_bad: List[str] = []
        months_missing: List[str] = []

        year, month = from_year, from_month
        while (year, month) <= (to_year, to_month):
            mp = self._analyze_month(year, month, pd)
            per_month.append(mp)
            total_records += mp.records

            label = f"{year}-{month:02d}"
            if mp.status == "missing":
                months_missing.append(label)
                months_bad.append(label)
            elif mp.status == "bad":
                months_bad.append(label)

            # Avançar al mes següent
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1

        months_ok_count = len(per_month) - len(months_bad)

        # coverage_from / coverage_to: primer i últim mes amb parquet
        present = [mp for mp in per_month if mp.status != "missing"]
        coverage_from = ""
        coverage_to = ""
        if present:
            fm = present[0]
            lm = present[-1]
            coverage_from = f"{fm.year}-{fm.month:02d}-01"
            coverage_to = f"{lm.year}-{lm.month:02d}-{calendar.monthrange(lm.year, lm.month)[1]:02d}"

        delta_pct = 0.0
        if self.target_records > 0:
            delta_pct = round(
                (total_records - self.target_records) / self.target_records * 100, 4
            )

        return ParityReport(
            symbol=self.symbol,
            tf=self.tf,
            generated_at=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            total_records=total_records,
            target_records=self.target_records,
            delta_vs_target_pct=delta_pct,
            coverage_from=coverage_from,
            coverage_to=coverage_to,
            months_total=len(per_month),
            months_ok=months_ok_count,
            months_bad=months_bad,
            months_missing=months_missing,
            thresholds={
                "min_records_ratio": self.min_records_ratio,
                "max_flat_ratio": self.max_flat_ratio,
            },
            per_month=per_month,
        )

    # ------------------------------------------------------------------
    # Helpers privats
    # ------------------------------------------------------------------

    def _parquet_path(self, year: int, month: int) -> Path:
        # Nota: parquet_store escriu month={MM} amb zero-padding (month=01, month=02...)
        # Cal usar el mateix format per localitzar els fitxers.
        return (
            self._root
            / "historical_parquet"
            / self.symbol
            / f"tf={self.tf}"
            / f"year={year}"
            / f"month={month:02d}"
            / "data.parquet"
        )

    def _expected_minutes(self, year: int, month: int) -> int:
        """
        Minuts esperats per un mes EURUSD M1.

        FX opera 24h/dia els dies laborables (dl-dv).
        Comptant dies laborables (weekday 0-4) i multiplicant per 1440.
        """
        _, days_in_month = calendar.monthrange(year, month)
        business_days = sum(
            1
            for d in range(1, days_in_month + 1)
            if datetime(year, month, d).weekday() < 5  # 0=dl, 4=dv
        )
        return business_days * 1440

    def _analyze_month(self, year: int, month: int, pd) -> MonthParity:
        """Llegeix el parquet d'un mes i calcula les mètriques."""
        path = self._parquet_path(year, month)
        expected = self._expected_minutes(year, month)

        if not path.exists():
            return MonthParity(
                year=year,
                month=month,
                records=0,
                expected_minutes=expected,
                completeness_ratio=0.0,
                flat_bars=0,
                flat_bars_ratio=0.0,
                status="missing",
            )

        try:
            df = pd.read_parquet(path)
        except Exception:
            # Fitxer corrupte → tractar com missing
            return MonthParity(
                year=year,
                month=month,
                records=0,
                expected_minutes=expected,
                completeness_ratio=0.0,
                flat_bars=0,
                flat_bars_ratio=0.0,
                status="missing",
            )

        records = len(df)

        if records == 0:
            return MonthParity(
                year=year,
                month=month,
                records=0,
                expected_minutes=expected,
                completeness_ratio=0.0,
                flat_bars=0,
                flat_bars_ratio=0.0,
                status="missing",
            )

        # Flat bars: O=H=L=C
        flat_bars = int(
            (
                (df["open"] == df["high"])
                & (df["high"] == df["low"])
                & (df["low"] == df["close"])
            ).sum()
        )
        flat_ratio = round(flat_bars / records, 6)

        completeness = round(records / expected, 6) if expected > 0 else 1.0

        # Determinar status
        is_bad = (
            records < expected * self.min_records_ratio
            or flat_ratio > self.max_flat_ratio
        )
        status = "bad" if is_bad else "ok"

        return MonthParity(
            year=year,
            month=month,
            records=records,
            expected_minutes=expected,
            completeness_ratio=completeness,
            flat_bars=flat_bars,
            flat_bars_ratio=flat_ratio,
            status=status,
        )

    def _resolve_range(
        self,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> tuple[int, int, int, int]:
        """
        Retorna (from_year, from_month, to_year, to_month).

        Si from_date és None: usa el primer mes disponible als parquets
        o per defecte 2003-01 (DUKASCOPY_EARLIEST).
        Si to_date és None: usa avui.
        """
        # Parse from_date
        if from_date:
            fd = datetime.strptime(from_date[:7], "%Y-%m")
            from_year, from_month = fd.year, fd.month
        else:
            # Detectar primer mes disponible
            base = self._root / "historical_parquet" / self.symbol / f"tf={self.tf}"
            first = self._find_first_month(base)
            if first:
                from_year, from_month = first
            else:
                from_year, from_month = 2003, 1

        # Parse to_date
        if to_date:
            td = datetime.strptime(to_date[:7], "%Y-%m")
            to_year, to_month = td.year, td.month
        else:
            now = datetime.now(tz=timezone.utc)
            to_year, to_month = now.year, now.month

        return from_year, from_month, to_year, to_month

    def _find_first_month(self, base_path: Path) -> Optional[tuple[int, int]]:
        """Troba el (year, month) del primer parquet disponible."""
        if not base_path.exists():
            return None
        years = sorted(
            int(p.name.split("=")[1])
            for p in base_path.iterdir()
            if p.is_dir() and p.name.startswith("year=")
        )
        for year in years:
            year_path = base_path / f"year={year}"
            months = sorted(
                int(p.name.split("=")[1])
                for p in year_path.iterdir()
                if p.is_dir() and p.name.startswith("month=")
            )
            for month in months:
                p = year_path / f"month={month:02d}" / "data.parquet"
                if p.exists() and p.stat().st_size > 0:
                    return (year, month)
        return None
