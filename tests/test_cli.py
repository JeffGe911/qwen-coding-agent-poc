from qwen_agent.cli import interactive
from qwen_agent import workflow
from test_workflow import GOOD, FakeModel


def test_demo_enter_leaves_pending(tmp_path, monkeypatch):
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, FakeModel([GOOD]))
    monkeypatch.setattr("builtins.input", lambda *args: "")
    state = interactive(run, state, "fixture")
    assert state["status"] == "awaiting_approval"
    assert not (run / "attempt-1" / "job").exists()


def test_demo_eof_leaves_pending(tmp_path, monkeypatch):
    run, state = workflow.start("clamp", tmp_path, "http://127.0.0.1:1/v1", "fixture", "restricted", 1, FakeModel([GOOD]))
    def eof(*args):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    state = interactive(run, state, "fixture")
    assert state["status"] == "awaiting_approval"
    assert not (run / "attempt-1" / "job").exists()
