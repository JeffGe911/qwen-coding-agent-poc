"""Acceptance tests for summarize_results. Frozen: see frozen.json. Sent to the model."""
import copy

import pytest
from solution import summarize_results


def records(*statuses):
    return [{"name": f"case_{i}", "status": status} for i, status in enumerate(statuses)]


def test_mixed_results():
    results = [
        {"name": "login", "status": "passed"},
        {"name": "permissions", "status": "passed"},
        {"name": "export", "status": "failed"},
        {"name": "external_device", "status": "skipped"},
    ]
    assert summarize_results(results) == {"passed": 2, "failed": 1, "skipped": 1, "pass_rate": 0.6667}


def test_empty_list():
    assert summarize_results([]) == {"passed": 0, "failed": 0, "skipped": 0, "pass_rate": 0.0}


def test_all_skipped():
    assert summarize_results(records("skipped", "skipped")) == {"passed": 0, "failed": 0, "skipped": 2, "pass_rate": 0.0}


def test_all_passed():
    assert summarize_results(records("passed", "passed", "passed")) == {"passed": 3, "failed": 0, "skipped": 0, "pass_rate": 1.0}


def test_all_failed():
    assert summarize_results(records("failed", "failed")) == {"passed": 0, "failed": 2, "skipped": 0, "pass_rate": 0.0}


def test_rounding_to_four_decimals():
    assert summarize_results(records("passed", "failed", "failed"))["pass_rate"] == 0.3333
    assert summarize_results(records("passed", *["failed"] * 6))["pass_rate"] == 0.1429


def test_unknown_status_raises_value_error():
    with pytest.raises(ValueError):
        summarize_results(records("passed", "flaky"))


def test_missing_status_raises_value_error():
    with pytest.raises(ValueError):
        summarize_results([{"name": "login", "status": "passed"}, {"name": "no_status"}])


def test_input_is_not_modified():
    results = records("passed", "failed", "skipped")
    before = copy.deepcopy(results)
    summarize_results(results)
    assert results == before
