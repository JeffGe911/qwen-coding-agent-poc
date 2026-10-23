import pytest
from solution import summarize_results


def test_internal_test_run():
    results = [
        {"name": "login", "status": "passed"},
        {"name": "permissions", "status": "passed"},
        {"name": "export", "status": "failed"},
        {"name": "external_device", "status": "skipped"},
    ]
    actual = summarize_results(results)
    assert actual["pass_rate"] == 0.6667, "Exclude skipped tests: round(2 / (2 + 1), 4), not 2 / 4"
    assert actual == {
        "passed": 2, "failed": 1, "skipped": 1, "pass_rate": 0.6667
    }


def test_empty_run():
    assert summarize_results([]) == {
        "passed": 0, "failed": 0, "skipped": 0, "pass_rate": 0.0
    }


def test_only_skipped():
    assert summarize_results([{"status": "skipped"}])["pass_rate"] == 0.0


def test_unknown_status():
    with pytest.raises(ValueError):
        summarize_results([{"status": "unknown"}])


def test_missing_status_must_raise_value_error_not_key_error():
    with pytest.raises(ValueError):
        summarize_results([{"name": "incomplete"}])
