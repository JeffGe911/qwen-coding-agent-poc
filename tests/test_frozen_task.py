"""Guards the frozen report_pass_rate acceptance tests. Framework test, not a model result."""
import hashlib
import json
import shutil

from qwen_agent.runner import execute
from qwen_agent.workflow import FILES, TASKS

TASK = TASKS / "report_pass_rate"

# Used only to prove the frozen tests are satisfiable. Never sent to the model:
# the client sends task.json description, solution.py and test_visible.py only.
REFERENCE = '''def summarize_results(results):
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        status = result.get("status")
        if status not in counts:
            raise ValueError(f"unknown or missing status: {status!r}")
        counts[status] += 1
    executed = counts["passed"] + counts["failed"]
    rate = round(counts["passed"] / executed, 4) if executed else 0.0
    return {"passed": counts["passed"], "failed": counts["failed"], "skipped": counts["skipped"], "pass_rate": rate}
'''


def run_with(tmp_path, code=None):
    for name in FILES:
        shutil.copy(TASK / name, tmp_path / name)
    if code is not None:
        (tmp_path / "solution.py").write_text(code, encoding="utf-8")
    return execute(tmp_path, "restricted")


def test_task_files_match_frozen_digests():
    frozen = json.loads((TASK / "frozen.json").read_text(encoding="utf-8"))
    for name, expected in frozen["sha256"].items():
        assert hashlib.sha256((TASK / name).read_bytes()).hexdigest() == expected, f"{name} changed after freezing"


def test_original_code_fails_baseline(tmp_path):
    result = run_with(tmp_path)
    assert (result["exit_code"], result["tests"], result["passed"], result["errors"]) == (1, 21, 8, 0)


def test_reference_solution_passes_everything(tmp_path):
    result = run_with(tmp_path, REFERENCE)
    assert (result["exit_code"], result["tests"], result["passed"]) == (0, 21, 21)


def test_holdout_is_not_in_model_prompt(monkeypatch):
    from qwen_agent.client import Client
    sent = {}
    monkeypatch.setattr(Client, "request", lambda self, path, body=None: sent.setdefault("body", body))
    task = json.loads((TASK / "task.json").read_text(encoding="utf-8"))
    Client("http://127.0.0.1:1/v1", "fixture").propose(task, (TASK / "solution.py").read_text(), (TASK / "test_visible.py").read_text(), "")
    prompt = json.dumps(sent["body"], ensure_ascii=False)
    assert "test_large_run" not in prompt and "h_" not in prompt
    assert "test_missing_status_raises_value_error" in prompt
