"""Holdout tests. Frozen: see frozen.json. NEVER sent to the model; failures are not fed back.

Every case follows from the written requirement; none adds a new rule.
"""
import copy

import pytest
from solution import summarize_results


def records(*statuses):
    return [{"name": f"h_{i}", "status": status} for i, status in enumerate(statuses)]


def test_exact_keys_and_value_types():
    summary = summarize_results(records("passed", "skipped"))
    assert set(summary) == {"passed", "failed", "skipped", "pass_rate"}
    assert all(type(summary[key]) is int for key in ("passed", "failed", "skipped"))
    assert type(summary["pass_rate"]) is float


def test_no_executed_cases_pass_rate_is_float_zero():
    summary = summarize_results(records("skipped"))
    assert summary["pass_rate"] == 0.0 and type(summary["pass_rate"]) is float


def test_skips_never_enter_denominator():
    assert summarize_results(records("passed", "passed", "failed", *["skipped"] * 5))["pass_rate"] == 0.6667
    assert summarize_results(records("passed", *["skipped"] * 9))["pass_rate"] == 1.0


def test_large_run():
    summary = summarize_results(records(*(["passed"] * 600 + ["failed"] * 150 + ["skipped"] * 250)))
    assert summary == {"passed": 600, "failed": 150, "skipped": 250, "pass_rate": 0.8}


@pytest.mark.parametrize("status", ["PASSED", "pass", "", None, "error"])
def test_other_unknown_statuses_raise_value_error(status):
    with pytest.raises(ValueError):
        summarize_results([{"name": "x", "status": status}])


def test_unknown_status_first_record_raises_value_error():
    with pytest.raises(ValueError):
        summarize_results([{"status": "unknown"}, {"status": "passed"}])


def test_input_unchanged_even_when_raising():
    results = [{"name": "a", "status": "passed"}, {"name": "b", "status": "bogus"}]
    before = copy.deepcopy(results)
    with pytest.raises(ValueError):
        summarize_results(results)
    assert results == before


def test_extra_fields_are_ignored():
    results = [{"name": "a", "status": "passed", "duration_ms": 12}, {"name": "b", "status": "failed", "owner": "qa"}]
    assert summarize_results(results) == {"passed": 1, "failed": 1, "skipped": 0, "pass_rate": 0.5}
