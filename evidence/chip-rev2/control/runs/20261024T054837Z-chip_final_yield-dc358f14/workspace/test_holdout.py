"""Holdout tests. Frozen: see frozen.json. NEVER sent to the model; failures are not fed back.

Every case follows from the written requirement; none adds a new rule.
"""
import copy

import pytest
from solution import summarize_chip_yield

REQUIRED = ["VREF", "IDDQ"]


def row(chip, item, value, unit="V", lower="1.19", upper="1.21", retest="0"):
    if item == "IDDQ" and lower == "1.19":
        lower, upper = "0", "0.005"
    return {"chip_id": chip, "test_item": item, "value": value, "unit": unit, "lower": lower, "upper": upper, "retest": retest}


def test_retest_compared_as_integer():
    rows = [row("D01", "VREF", "1.2000", retest="10"), row("D01", "VREF", "1.1500", retest="9"), row("D01", "IDDQ", "0.0021")]
    assert summarize_chip_yield(rows, REQUIRED)["passed_chips"] == 1


def test_final_round_listed_before_earlier_rounds():
    rows = [row("D01", "VREF", "1.1500", retest="2"), row("D01", "VREF", "1.2000", retest="0"), row("D01", "IDDQ", "0.0021")]
    assert summarize_chip_yield(rows, REQUIRED)["failed_chip_ids"] == ["D01"]


def test_missing_value_only_counts_on_final_result():
    rows = [row("D01", "VREF", "", retest="0"), row("D01", "VREF", "1.2000", retest="1"), row("D01", "IDDQ", "0.0021")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["passed_chips"] == 1 and result["missing_values"] == 0


def test_missing_final_value_after_earlier_pass_fails():
    rows = [row("D01", "VREF", "1.2000", retest="0"), row("D01", "VREF", "", retest="1"), row("D01", "IDDQ", "0.0021")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["passed_chips"] == 0 and result["missing_values"] == 1


def test_duplicate_of_retest_row_is_not_a_conflict():
    retest = row("D01", "VREF", "1.1950", retest="1")
    rows = [row("D01", "VREF", "1.1850"), retest, dict(retest), row("D01", "IDDQ", "0.0021")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["duplicates_ignored"] == 1 and result["passed_chips"] == 1


def test_millivolt_value_inside_limits():
    rows = [row("D01", "VREF", "1205.5", unit="mV"), row("D01", "IDDQ", "0.0021")]
    assert summarize_chip_yield(rows, REQUIRED)["passed_chips"] == 1


def test_yield_rounded_to_four_decimals_and_ids_sorted():
    rows = []
    for chip in ("D03", "D01", "D02"):
        rows += [row(chip, "VREF", "1.2000"), row(chip, "IDDQ", "0.0061" if chip == "D03" else "0.0021")]
    rows += [row("D00", "VREF", "1.1000"), row("D00", "IDDQ", "0.0021")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["yield"] == 0.5 and result["failed_chip_ids"] == ["D00", "D03"]
    rows = [r for r in rows if r["chip_id"] != "D00"]
    assert summarize_chip_yield(rows, REQUIRED)["yield"] == 0.6667


def test_non_required_items_do_not_decide_the_chip():
    rows = [row("D01", "VREF", "1.2000"), row("D01", "IDDQ", "0.0021"), row("D01", "LEAK", "9.9", lower="0", upper="1"),
            row("D02", "LEAK", "0.5", lower="0", upper="1")]
    result = summarize_chip_yield(rows, REQUIRED)
    assert result["chips"] == 2 and result["failed_chip_ids"] == ["D02"]


def test_types_and_exact_keys():
    result = summarize_chip_yield([row("D01", "VREF", "1.2000"), row("D01", "IDDQ", "0.0021")], REQUIRED)
    assert set(result) == {"chips", "passed_chips", "yield", "failed_chip_ids", "duplicates_ignored", "missing_values"}
    assert type(result["yield"]) is float and type(result["chips"]) is int and isinstance(result["failed_chip_ids"], list)


def test_no_chip_passes_gives_float_zero():
    result = summarize_chip_yield([row("D01", "VREF", "1.1000"), row("D01", "IDDQ", "0.0021")], REQUIRED)
    assert result["yield"] == 0.0 and type(result["yield"]) is float


def test_input_unchanged_when_raising():
    rows = [row("D01", "VREF", "1.2000"), row("D01", "IDDQ", "1.0", unit="A")]
    before = copy.deepcopy(rows)
    with pytest.raises(ValueError):
        summarize_chip_yield(rows, REQUIRED)
    assert rows == before
