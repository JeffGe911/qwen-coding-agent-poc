import json
import pytest
from qwen_agent import workflow
from qwen_agent.policy import digest
from qwen_agent.runner import execute

GOOD = "def clamp(value, lower, upper):\n    if lower > upper:\n        raise ValueError('invalid bounds')\n    return min(max(value, lower), upper)\n"
BAD = "def clamp(value, lower, upper):\n    return value + 0\n"
BAD2 = "def clamp(value, lower, upper):\n    return value - 0\n"


class FakeModel:
    """Test fixture, not a live Qwen result. A None entry simulates malformed model output."""
    def __init__(self, codes):
        self.codes = iter(codes)
        self.calls = 0

    def propose(self, *args):
        self.calls += 1
        code = next(self.codes)
        content = "not json" if code is None else json.dumps({"code": code, "explanation": "test fixture, not a live Qwen result"})
        return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


def start(tmp_path, codes=None, attempts=3):
    return workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "test-fixture", "restricted", attempts, FakeModel(codes or [GOOD]))


def test_real_pytest_baseline_then_approved_repair(tmp_path):
    original = (workflow.TASKS / "clamp" / "solution.py").read_bytes()
    run, state = start(tmp_path)
    assert state["baseline"]["exit_code"] == 1
    assert state["baseline"]["tests"] == 8
    assert state["status"] == "awaiting_approval"
    assert not (run / "attempt-1" / "job").exists()
    state = workflow.decide(run, "approve", state["attempts"][0]["digest"], "unit-test-human-fixture")
    assert state["status"] == "succeeded"
    assert state["attempts"][0]["result"]["passed"] == 8
    assert (workflow.TASKS / "clamp" / "solution.py").read_bytes() == original
    events = [json.loads(line)["type"] for line in (run / "events.jsonl").read_text().splitlines()]
    assert events.index("approve") < events.index("pytest_finished")
    with pytest.raises(ValueError, match="not awaiting"):
        workflow.decide(run, "approve", state["attempts"][0]["digest"], "fixture")


def test_reject_never_executes(tmp_path, monkeypatch):
    run, state = start(tmp_path)
    monkeypatch.setattr(workflow, "execute", lambda *a: pytest.fail("Rejected code must not run"))
    state = workflow.decide(run, "reject", state["attempts"][0]["digest"], "fixture")
    assert state["status"] == "rejected"
    assert not (run / "attempt-1" / "job").exists()


@pytest.mark.parametrize("target", ["proposal", "test", "config", "digest"])
def test_tampering_invalidates_approval(tmp_path, monkeypatch, target):
    run, state = start(tmp_path)
    token = state["attempts"][0]["digest"]
    if target == "proposal":
        path = run / "attempt-1" / "proposal.json"
        proposal = workflow.read_json(path)
        proposal["code"] = BAD
        workflow.write_json(path, proposal)
    elif target == "test":
        (run / "workspace" / "test_visible.py").write_text("assert True")
    elif target == "config":
        state["config"]["timeout_seconds"] = 999
        workflow.write_json(run / "state.json", state)
    else:
        token = digest("wrong")
    monkeypatch.setattr(workflow, "execute", lambda *a: pytest.fail("Tampered approval must not execute"))
    with pytest.raises(ValueError, match="mismatch"):
        workflow.decide(run, "approve", token, "fixture")


def test_retry_requires_new_approval_and_budget_is_enforced(tmp_path):
    model = FakeModel([BAD, BAD2])
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "test-fixture", "restricted", 2, model)
    state = workflow.decide(run, "approve", state["attempts"][0]["digest"], "fixture", model)
    assert state["status"] == "awaiting_approval"
    assert state["attempts"][0]["status"] == "failed"
    assert not (run / "attempt-2" / "job").exists()
    state = workflow.decide(run, "approve", state["attempts"][1]["digest"], "fixture", model)
    assert state["status"] == "failed"
    assert state["stop_reason"] == "proposal_budget_exhausted"
    assert len(state["attempts"]) == 2


def test_policy_blocked_code_cannot_be_approved(tmp_path):
    run, state = start(tmp_path, ["import os\n"], attempts=1)
    assert state["stop_reason"] == "proposal_budget_exhausted"
    assert state["status"] == "policy_blocked"
    with pytest.raises(ValueError, match="not awaiting"):
        workflow.decide(run, "approve", state["attempts"][0]["digest"], "fixture")


def test_worker_timeout(tmp_path):
    for name in workflow.FILES:
        (tmp_path / name).write_text((workflow.TASKS / "clamp" / name).read_text())
    (tmp_path / "solution.py").write_text("def clamp(value, lower, upper):\n    return clamp(value, lower, upper)\n")
    # Tiny timeout deterministically verifies parent kill/reap, including startup.
    result = execute(tmp_path, "restricted", timeout=0.001)
    assert result["timeout"] is True


def test_unknown_task_and_concurrent_lock(tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        workflow.start("../clamp", tmp_path, "http://127.0.0.1/v1", "fixture")
    with workflow.lock(tmp_path):
        with pytest.raises(ValueError, match="locked"):
            with workflow.lock(tmp_path):
                pass


def test_unchanged_code_finishes_without_execution(tmp_path):
    run, state = start(tmp_path, ["def clamp(value, lower, upper):\n    return value\n"])
    assert state["status"] == "failed"
    assert state["attempts"][0]["status"] == "no_change"
    assert not (run / "attempt-1" / "job").exists()


def test_policy_block_auto_reproposes_with_feedback_and_needs_approval(tmp_path):
    run, state = start(tmp_path, ["import os\n", GOOD])
    assert state["status"] == "awaiting_approval"
    assert [a["status"] for a in state["attempts"]] == ["policy_blocked", "awaiting_approval"]
    assert "rejected by the code policy" in state["feedback"]
    assert not (run / "attempt-2" / "job").exists()
    events = [json.loads(line)["type"] for line in (run / "events.jsonl").read_text().splitlines()]
    assert "auto_repropose" in events and "approve" not in events


def test_model_error_manual_retry_gets_new_pending_proposal(tmp_path):
    run, state = start(tmp_path, [None])
    assert state["status"] == "model_error"
    state = workflow.retry(run, FakeModel([GOOD]))
    assert state["status"] == "awaiting_approval"
    assert len(state["attempts"]) == 2
    assert not (run / "attempt-2" / "job").exists()


def test_repeated_blocked_proposal_stops_without_spending_budget(tmp_path):
    model = FakeModel(["import os\n", "import os\n", GOOD])
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "test-fixture", "restricted", 3, model)
    assert state["status"] == "policy_blocked"
    assert state["stop_reason"] == "duplicate_proposal"
    assert [a["status"] for a in state["attempts"]] == ["policy_blocked", "duplicate"]
    assert model.calls == 2
    with pytest.raises(ValueError, match="stopped"):
        workflow.retry(run, FakeModel([GOOD]))


def test_repeating_an_earlier_failed_proposal_stops(tmp_path):
    model = FakeModel([BAD, BAD2, BAD])
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "test-fixture", "restricted", 3, model)
    state = workflow.decide(run, "approve", state["attempts"][0]["digest"], "fixture", model)
    state = workflow.decide(run, "approve", state["attempts"][1]["digest"], "fixture", model)
    assert state["status"] == "failed"
    assert state["stop_reason"] == "duplicate_proposal"
    assert state["attempts"][2]["status"] == "duplicate"
    assert not (run / "attempt-3" / "job").exists()


def test_contract_is_recorded_and_bound_into_approval(tmp_path):
    run, state = start(tmp_path)
    frozen = state["config"]["contract"]
    assert set(frozen) == {"prompt_sha256", "policy_revision", "policy_sha256", "task_files_sha256"}
    assert set(frozen["task_files_sha256"]) == {"solution.py", "test_visible.py", "test_holdout.py", "task.json"}
    state["config"]["contract"]["prompt_sha256"] = "0" * 64
    workflow.write_json(run / "state.json", state)
    with pytest.raises(ValueError, match="mismatch"):
        workflow.decide(run, "approve", state["attempts"][0]["digest"], "fixture")


def test_candidate_missing_api_is_model_failure_not_infrastructure(tmp_path):
    run, state = start(tmp_path, ["def another_function():\n    return 1\n"], attempts=1)
    state = workflow.decide(run, "approve", state["attempts"][0]["digest"], "fixture")
    assert state["status"] == "failed"
    assert state["attempts"][0]["result"]["exit_code"] == 2

