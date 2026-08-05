"""Tests purs del walk-forward amb costos de sq_0423850."""

from datetime import datetime, timezone

from lab.runner.walk_forward_sq_0423850 import (
    CostScenario,
    evaluate,
    metrics,
    net_values,
)


def _ts(year: int, month: int = 1, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def _trade(year: int, gross_pct: float, holding_days: int = 0) -> dict:
    entry = _ts(year)
    return {
        "entry_ts": entry,
        "exit_ts": entry + holding_days * 86400,
        "pnl_pct": gross_pct,
    }


def test_cost_formula():
    scenario = CostScenario("test", 3, 2, 1, 365)
    values = net_values([_trade(2020, 1.0, holding_days=10)], scenario)
    expected = 1.0 - 0.06 - (365 * 10 / 365.25) / 100
    assert abs(values[0] - expected) < 0.0001


def test_metrics_compound_and_profit_factor():
    scenario = CostScenario("gross", 0, 0, 0, 0)
    result = metrics([_trade(2020, 10), _trade(2020, -10)], scenario)
    assert result["n"] == 2
    assert result["compound_pct"] == -1.0
    assert result["profit_factor"] == 1.0
    assert result["max_dd_pct"] == 10.0


def test_evaluate_separates_train_and_oos():
    scenario = CostScenario("gross", 0, 0, 0, 0)
    trades = [_trade(year, 1 if year % 2 else -1) for year in range(2016, 2023)]
    result = evaluate(trades, scenario, 2016, 2023, train_years=3)
    assert result["train"]["window"] == "2016-2018"
    assert result["train"]["n"] == 3
    assert result["oos"]["window"] == "2019-2022"
    assert result["oos"]["n"] == 4
    assert result["oos"]["positive_years"] == 2
    assert result["oos"]["total_years"] == 4


if __name__ == "__main__":
    test_cost_formula()
    test_metrics_compound_and_profit_factor()
    test_evaluate_separates_train_and_oos()
    print("OK test_walk_forward_sq_0423850")
