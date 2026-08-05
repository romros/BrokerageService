"""Walk-forward temporal de sq_0423850 amb costos Ostium explícits.

Llegeix Parquet M1 local, agrega a H4 i avalua finestres anuals amb els
paràmetres congelats. No executa ordres ni usa xarxa.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from lab.runner.backtest.run_backtest import (
    compute_atr,
    load_strategy_config,
    load_strategy_fn,
    simulate_trades,
)

SECONDS_PER_YEAR = 365.25 * 86400


@dataclass(frozen=True, slots=True)
class CostScenario:
    name: str
    opening_fee_bps: float
    spread_bps: float
    slippage_bps: float
    rollover_annual_bps: float


SCENARIOS = (
    CostScenario("official_base", 3, 2, 1, 200),
    CostScenario("conservative", 3, 5, 2, 500),
    CostScenario("stress", 3, 10, 5, 1000),
)


def load_h4(root: Path, symbol: str, date_from: str, date_to: str) -> pd.DataFrame:
    """Agrega els Parquet M1 a H4 dins DuckDB."""
    import duckdb

    dataset = root / symbol / "tf=1m"
    if not dataset.exists():
        raise FileNotFoundError(dataset)
    start = int(datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc).timestamp())
    end = int(datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc).timestamp())
    query = """
        SELECT cast(floor(ts/14400)*14400 AS BIGINT) AS ts,
               arg_min(open,ts) AS open, max(high) AS high, min(low) AS low,
               arg_max(close,ts) AS close_price, sum(volume) AS volume
        FROM read_parquet(?, hive_partitioning=false)
        WHERE ts>=? AND ts<? GROUP BY 1 ORDER BY 1
    """
    df = duckdb.connect().execute(
        query, [str(dataset / "**" / "*.parquet"), start, end]
    ).fetchdf().rename(columns={"close_price": "close"})
    if df.empty:
        raise RuntimeError(f"Dataset buit: {symbol} {date_from} to {date_to}")
    df["_ts"] = df["ts"].astype("int64")
    df.index = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df[["open", "high", "low", "close", "volume", "_ts"]]


def net_values(trades: list[dict[str, Any]], scenario: CostScenario) -> np.ndarray:
    values = []
    execution_bps = scenario.opening_fee_bps + scenario.spread_bps + scenario.slippage_bps
    for trade in trades:
        holding_s = max(0, int(trade["exit_ts"]) - int(trade["entry_ts"]))
        rollover_bps = scenario.rollover_annual_bps * holding_s / SECONDS_PER_YEAR
        values.append(float(trade["pnl_pct"]) - (execution_bps + rollover_bps) / 100)
    return np.asarray(values, dtype=float)


def metrics(trades: list[dict[str, Any]], scenario: CostScenario) -> dict[str, Any]:
    values = net_values(trades, scenario)
    if not len(values):
        return {"n": 0, "sum_pct": 0.0, "compound_pct": 0.0, "wr_pct": 0.0,
                "profit_factor": None, "max_dd_pct": 0.0, "avg_pct": 0.0}
    equity = np.cumprod(1 + values / 100)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))[:-1]
    drawdown = np.maximum(0, (peaks - equity) / peaks * 100)
    wins = float(values[values > 0].sum())
    losses = abs(float(values[values <= 0].sum()))
    return {
        "n": len(values),
        "sum_pct": round(float(values.sum()), 4),
        "compound_pct": round(float((equity[-1] - 1) * 100), 4),
        "wr_pct": round(float(np.mean(values > 0) * 100), 2),
        "profit_factor": round(wins / losses, 4) if losses else None,
        "max_dd_pct": round(float(drawdown.max()), 4),
        "avg_pct": round(float(values.mean()), 4),
    }


def trade_year(trade: dict[str, Any]) -> int:
    return datetime.fromtimestamp(int(trade["entry_ts"]), timezone.utc).year


def evaluate(trades: list[dict[str, Any]], scenario: CostScenario,
             first_year: int, last_year: int, train_years: int) -> dict[str, Any]:
    train_end = first_year + train_years
    annual = []
    for year in range(first_year, last_year):
        result = metrics([t for t in trades if trade_year(t) == year], scenario)
        annual.append({"year": year, **result, "positive": result["compound_pct"] > 0})
    train = [t for t in trades if first_year <= trade_year(t) < train_end]
    oos = [t for t in trades if train_end <= trade_year(t) < last_year]
    oos_metrics = metrics(oos, scenario)
    oos_annual = [row for row in annual if row["year"] >= train_end]
    positive = sum(row["positive"] for row in oos_annual)
    return {
        "scenario": asdict(scenario),
        "train": {"window": f"{first_year}-{train_end-1}", **metrics(train, scenario)},
        "oos": {"window": f"{train_end}-{last_year-1}", **oos_metrics,
                "positive_years": positive, "total_years": len(oos_annual)},
        "years": annual,
    }


def write_report(out_dir: Path, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "walk_forward_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    rows = [{"scenario": result["scenario"]["name"], **year}
            for result in report["results"] for year in result["years"]]
    with (out_dir / "walk_forward_windows.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# sq_0423850 XAUUSD H4 — walk-forward amb costos", "",
        "**Decisió: REJECTED_OOS. No activar com a estratègia paper candidata.**", "",
        "Paràmetres congelats. Train 2016–2018; finestres OOS anuals 2019–2025.", "",
        "| Escenari | Trades OOS | Retorn compost | PF | Max DD | Anys positius |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in report["results"]:
        scenario_name = result["scenario"]["name"]
        oos = result["oos"]
        lines.append(
            "| {scenario} | {n} | {compound_pct:.2f}% | {profit_factor} | "
            "{max_dd_pct:.2f}% | {positive_years}/{total_years} |".format(
                scenario=scenario_name, **oos
            )
        )
    lines += ["", "Costos: fee obertura + bid/ask + slippage + rollover per holding.",
              "Oracle net zero en full close correcte. Sense ordres ni capital real."]
    (out_dir / "CONCLUSIONS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet-root", type=Path, default=Path("datafiles/historical_parquet"))
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--from", dest="date_from", default="2016-01-01")
    parser.add_argument("--to", dest="date_to", default="2026-01-01")
    parser.add_argument("--train-years", type=int, default=3)
    parser.add_argument("--out-dir", type=Path, default=Path("lab/out/walkforward_sq_0423850"))
    args = parser.parse_args()
    first_year, last_year = int(args.date_from[:4]), int(args.date_to[:4])
    if args.train_years < 1 or first_year + args.train_years >= last_year:
        raise ValueError("train-years ha de deixar almenys un any OOS")
    df = load_h4(args.parquet_root, args.symbol, args.date_from, args.date_to)
    config = load_strategy_config("sq_0423850")
    signals = load_strategy_fn("sq_0423850")(df)
    atr = compute_atr(df, int(config.get("atr_period", 10)))
    trades = simulate_trades(df, signals, atr, config, intrabar_mode="sl_first")
    gross = metrics(trades, CostScenario("gross", 0, 0, 0, 0))
    results = [evaluate(trades, scenario, first_year, last_year, args.train_years)
               for scenario in SCENARIOS]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "sq_0423850", "symbol": args.symbol, "timeframe": "4h",
        "from": args.date_from, "to": args.date_to, "train_years": args.train_years,
        "method": "fixed parameters; initial train then annual anchored OOS",
        "data_source": str(args.parquet_root),
        "data_note": "legacy Dukascopy M1 parquet; API 10y query timed out",
        "gross": gross, "results": results,
    }
    write_report(args.out_dir, report)
    print(json.dumps({"gross": gross, "oos": {r["scenario"]["name"]: r["oos"]
          for r in results}, "out_dir": str(args.out_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
