from qwen_agent.report import generate, summarize
from qwen_agent.workflow import write_json


def state(status, model="fixture"):
    return {"run_id": "test-" + status, "status": status, "config": {"model": model, "sandbox": "restricted"}, "attempts": [{}]}


def test_denominators_and_zero_completed():
    summary = summarize([state("succeeded"), state("failed"), state("awaiting_approval"), state("policy_blocked"), state("infra_error")])
    assert summary["success_rate_completed"] == 0.5
    assert summary["success_rate_started"] == 0.2
    assert summary["completed_evaluations"] == 2
    assert summarize([])["success_rate_completed"] is None


def test_report_escapes_model_output(tmp_path):
    run = tmp_path / "runs" / "one"
    run.mkdir(parents=True)
    write_json(run / "state.json", state("awaiting_approval", "<script>alert(1)</script>"))
    generate(run.parent, tmp_path / "out")
    report = (tmp_path / "out" / "report.html").read_text(encoding="utf-8")
    assert "<script>alert" not in report
    assert "&lt;script&gt;" in report


def test_every_status_lands_in_exactly_one_category():
    statuses = ["succeeded", "failed", "awaiting_approval", "policy_blocked", "model_error", "infra_error", "rejected", "executing"]
    summary = summarize([state(s) for s in statuses])
    counts = {k: v["count"] for k, v in summary["categories"].items()}
    assert counts == {"task_success": 1, "repair_failed": 1, "pending_approval": 1, "policy_blocked": 1,
                      "model_api_error": 1, "infra_error": 2, "human_rejected": 1}
    assert sum(counts.values()) == summary["started_runs"] == 8
    assert summary["completed_evaluations"] == 2
