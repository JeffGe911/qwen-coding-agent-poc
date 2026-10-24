"""Acceptance tests for summarize_chip_yield. Frozen: see frozen.json. Sent to the model. SYNTHETIC rows."""
import copy

import pytest
from solution import summarize_chip_yield

REQUIRED = ["VREF", "IDDQ"]


def row(chip, item, value, unit="V", lower="1.19", upper="1.21", retest="0"):
    if item == "IDDQ" and lower == "1.19":
        lower, upper = "0", "0.005"
    return {"chip_id": chip, "test_item": item, "value": value, "unit": unit, "lower": lower, "upper": upper, "retest": retest}


def good(chip):
    return [row(chip, "VREF", "1.2000"), row(chip, "IDDQ", "0.0021")]


def test_normal_data():
    rows = good("D01") + [row("D02", "VREF", "1.2000"), row("D02", "IDDQ", "0.0061")]
    assert summarize_chip_yield(rows, REQUIRED) == {
        "chips": 2, "passed_chips": 1, "yield": 0.5, "failed_chip_ids": ["D02"], "duplicates_ignored": 0, "missing_values": 0}


def test_missing_value_counts_as_failure():
    rows = good("D01") + [row("D02", "VREF", "1.2000"), row("D02", "IDDQ", "")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["failed_chip_ids"] == ["D02"]
    assert result["missing_values"] == 1


def test_exact_duplicate_rows_counted_once():
    rows = good("D01") + [row("D01", "IDDQ", "0.0021")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["duplicates_ignored"] == 1
    assert result["chips"] == 1 and result["passed_chips"] == 1


def test_retest_highest_round_is_final():
    rows = [row("D01", "VREF", "1.1850", retest="0"), row("D01", "VREF", "1.1950", retest="1"), row("D01", "IDDQ", "0.0021")]
    assert summarize_chip_yield(rows, REQUIRED)["passed_chips"] == 1


def test_millivolt_values_are_converted():
    rows = [row("D01", "VREF", "1200.0", unit="mV"), row("D01", "IDDQ", "0.0021"),
            row("D02", "VREF", "1250.0", unit="mV"), row("D02", "IDDQ", "0.0021")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["passed_chips"] == 1 and result["failed_chip_ids"] == ["D02"]


def test_unknown_unit_raises_value_error():
    with pytest.raises(ValueError):
        summarize_chip_yield([row("D01", "VREF", "1.2", unit="kV")], REQUIRED)


def test_empty_file_returns_zero_summary():
    assert summarize_chip_yield([], REQUIRED) == {
        "chips": 0, "passed_chips": 0, "yield": 0.0, "failed_chip_ids": [], "duplicates_ignored": 0, "missing_values": 0}


def test_missing_required_item_fails_chip():
    rows = good("D01") + [row("D02", "VREF", "1.2000")]
    assert summarize_chip_yield(rows, REQUIRED)["failed_chip_ids"] == ["D02"]


def test_limits_are_inclusive():
    rows = [row("D01", "VREF", "1.19"), row("D01", "IDDQ", "0.005"), row("D02", "VREF", "1.21"), row("D02", "IDDQ", "0")]
    assert summarize_chip_yield(rows, REQUIRED)["passed_chips"] == 2


def test_conflicting_rows_in_same_round_raise_value_error():
    rows = good("D01") + [row("D01", "VREF", "1.2050")]
    with pytest.raises(ValueError):
        summarize_chip_yield(rows, REQUIRED)


def test_input_is_not_modified():
    rows = good("D01") + [row("D02", "VREF", "1200.0", unit="mV"), row("D02", "IDDQ", "")]
    before = copy.deepcopy(rows)
    summarize_chip_yield(rows, REQUIRED)
    assert rows == before
