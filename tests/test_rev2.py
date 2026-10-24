"""Contract revision 2 plumbing: generation profiles, fenced format, contract arms, per-file test counts, accepted failures.
Fixtures, not live model results."""
import json
import shutil

import pytest

from qwen_agent import workflow
from qwen_agent.cli import load_contract_arm
from qwen_agent.client import prompt_sha256
from qwen_agent.generation import check_profile, format_sha256, native_body, normalize_native, parse
from qwen_agent.runner import execute
from qwen_ops import release
from test_ops import FakeService

CONTRACT = workflow.TASKS.parent / "contracts" / "chip_final_yield" / "rev2.json"
GOOD = "def clamp(value, lower, upper):\n    if lower > upper:\n        raise ValueError('invalid bounds')\n    return min(max(value, lower), upper)\n"


def test_fenced_format_takes_exactly_one_block_and_records_the_cap():
    proposal, facts = parse("fenced_v1", "```python\n" + GOOD + "```\nClamps the value. Raises on bad bounds.")
    assert proposal["code"] == GOOD and facts["explanation_sentences"] == 2 and facts["explanation_cap_respected"]
    _, facts = parse("fenced_v1", "```python\n" + GOOD + "```\nOne. Two. Three. Four.")
    assert facts["explanation_sentences"] == 4 and not facts["explanation_cap_respected"]  # recorded, not enforced
    with pytest.raises(ValueError, match="found 0"):
        parse("fenced_v1", "def clamp(): pass")
    with pytest.raises(ValueError, match="found 2"):
        parse("fenced_v1", "```python\na = 1\n```\n```python\nb = 2\n```")
    with pytest.raises(ValueError):
        parse("json_v1", '{"code": "x"')


def test_profiles_state_every_sampling_value_and_json_v1_is_revision_1():
    arms = json.loads(CONTRACT.read_text(encoding="utf-8"))["arms"]
    for spec in arms.values():
        check_profile(spec["generation"])
    assert format_sha256("json_v1") == prompt_sha256() and format_sha256("fenced_v1") != prompt_sha256()
    body = native_body("m", arms["B"]["generation"], [{"role": "user", "content": "x"}])
    assert body["options"] == {**arms["B"]["generation"]["sampling"], "num_predict": 1600} and body["options"]["repeat_penalty"] == 1.1
    assert "format" in body and "format" not in native_body("m", arms["A"]["generation"], [])
    assert arms["control"]["generation"]["sampling"]["top_p"] == 1.0  # native default 0.9 must never apply
    with pytest.raises(ValueError, match="explicitly"):
        check_profile({"format": "json_v1", "transport": "ollama_native_chat", "max_tokens": 1600, "sampling": {"temperature": 0}})
    out = normalize_native({"message": {"content": "c"}, "done_reason": "length", "prompt_eval_count": 7, "eval_count": 9})
    assert out["choices"][0]["finish_reason"] == "length" and out["usage"] == {"prompt_tokens": 7, "completion_tokens": 9}


def test_contract_arm_is_checked_against_the_frozen_task_files(tmp_path):
    model, generation, window, revision = load_contract_arm(CONTRACT, "A", "chip_final_yield")
    assert model == "qwen2.5-coder:7b" and generation["format"] == "fenced_v1" and window == 8192 and revision["arm"] == "A" and len(revision["sha256"]) == 64
    with pytest.raises(ValueError, match="not report_pass_rate"):
        load_contract_arm(CONTRACT, "A", "report_pass_rate")
    with pytest.raises(ValueError, match="no arm"):
        load_contract_arm(CONTRACT, "Z", "chip_final_yield")
    doc = json.loads(CONTRACT.read_text(encoding="utf-8"))
    doc["task_files_sha256"]["test_holdout.py"] = "0" * 64
    tampered = tmp_path / "rev2.json"
    tampered.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="test_holdout.py differs"):
        load_contract_arm(tampered, "A", "chip_final_yield")


class ProfileModel:
    def __init__(self, content):
        self.content, self.kwargs = content, None

    def propose(self, *args, **kwargs):
        self.kwargs = kwargs
        return {"choices": [{"finish_reason": "stop", "message": {"content": self.content}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50}}


def test_run_config_records_the_arm_before_any_model_call(tmp_path):
    _, generation, window, revision = load_contract_arm(CONTRACT, "A", "chip_final_yield")
    model = ProfileModel("```python\n" + GOOD + "```\nFixed.")
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, model, context_tokens=window,
                                generation=generation, contract_revision=revision)
    assert state["status"] == "awaiting_approval" and model.kwargs == {"profile": generation}
    assert state["config"]["generation"] == generation and state["config"]["contract_revision"] == revision
    assert state["config"]["contract"]["prompt_sha256"] == format_sha256("fenced_v1") and state["attempts"][0]["format_facts"]["explanation_sentences"] == 1
    events = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[0]["type"] == "created" and events[0]["contract"]["prompt_sha256"] == format_sha256("fenced_v1")


def test_worker_reports_visible_and_holdout_separately(tmp_path):
    for name in workflow.FILES:
        shutil.copy(workflow.TASKS / "chip_final_yield" / name, tmp_path / name)
    result = execute(tmp_path, "restricted")
    assert (result["tests"], result["passed"]) == (22, 4)
    assert result["visible"] == {"tests": 11, "passed": 2} and result["holdout"] == {"tests": 11, "passed": 2}


@pytest.fixture
def releases(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "RELEASES", tmp_path)
    monkeypatch.setattr(release, "apply", lambda manifest, evidence_dir=None: (FakeService(), {"restarted": False}))
    monkeypatch.setattr(release, "verify_pins", lambda manifest, service: [])
    for name in ("r1", "r2"):
        (tmp_path / f"{name}.json").write_text(json.dumps({"name": name, "model": {"name": "m"}, "server": {"kind": "ollama-windows"}}), encoding="utf-8")
    (tmp_path / "ACTIVE").write_text("r1\n", encoding="utf-8")
    return tmp_path


def gate(health="healthy", chip=False):
    return lambda base_url, model, pid=None: {"passed": False, "checks": {"health_status": health, "proposals": {"report_pass_rate": True, "chip_final_yield": chip}}}


def test_known_failure_can_be_accepted_by_a_named_human_but_not_health(releases):
    accept = {"tasks": ["chip_final_yield"], "approved_by": "fixture", "reason": "fails on r1 too"}
    out = release.activate("r2", gate_fn=gate(), auto_rollback=False)
    assert out["active"] == "r1" and not out["accepted"]  # without acceptance the gate blocks
    out = release.activate("r2", gate_fn=gate(health="model_wrong_or_slow"), accept=accept, auto_rollback=False)
    assert out["active"] == "r1"  # an unhealthy service is never waivable
    out = release.activate("r2", gate_fn=gate(), accept=accept)
    assert out["active"] == "r2" and release.active_name() == "r2" and out["gate"]["passed"] is False
    last = release.read_history()[-1]
    assert last["accepted_failures"] == accept and last["activated_with_accepted_failures"] and last["gate_passed"] is False
    assert release.previous_release("r2") == "r1" or release.previous_release("r2") is None
