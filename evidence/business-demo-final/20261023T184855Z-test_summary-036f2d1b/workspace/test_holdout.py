import pytest
from solution import summarize_results


def test_missing_status():
    with pytest.raises(ValueError):
        summarize_results([{"name": "incomplete"}])


@pytest.mark.parametrize("statuses,rate", [
    (["passed"], 1.0),
    (["failed"], 0.0),
    (["passed", "failed", "failed"], 0.3333),
    (["passed", "skipped", "skipped"], 1.0),
])
def test_rates(statuses, rate):
    results = [{"status": status} for status in statuses]
    summary = summarize_results(results)
    assert summary["pass_rate"] == rate
    assert set(summary) == {"passed", "failed", "skipped", "pass_rate"}


def test_no_mutation():
    results = [{"name": "example", "status": "passed"}]
    summarize_results(results)
    assert results == [{"name": "example", "status": "passed"}]
