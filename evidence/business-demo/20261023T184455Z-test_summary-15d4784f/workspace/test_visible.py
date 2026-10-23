import pytest
from solution import summarize_results


def test_internal_test_run():
    results = [
        {"name": "login", "status": "passed"},
        {"name": "permissions", "status": "passed"},
        {"name": "export", "status": "failed"},
        {"name": "external_device", "status": "skipped"},
    ]
    assert summarize_results(results) == {
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
