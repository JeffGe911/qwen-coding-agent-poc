"""Safety and replay checks for public RAG entry points; no models are loaded."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_interactive_preflight_refuses_before_loading(monkeypatch):
    mod = load("ask_local_docs")
    monkeypatch.setattr(mod.resources, "memory", lambda: {"available_mb": 7000, "commit_headroom_mb": 12000})
    monkeypatch.setattr(mod.resources, "gpu", lambda: {"vram_free_mb": 12000})
    monkeypatch.setattr(mod.resources, "ac_power", lambda: True)
    with pytest.raises(mod.resources.ResourceError, match="available RAM"):
        mod.preflight()

def test_interactive_unloads_own_models_after_generation_exception(monkeypatch):
    mod = load("ask_local_docs")
    monkeypatch.setattr(mod, "preflight", lambda: {})
    monkeypatch.setattr(mod, "loaded", lambda profile: [])
    monkeypatch.setattr(mod.index, "Index", lambda path: type("FakeIndex", (), {"search": lambda self, *a, **k: []})())
    monkeypatch.setattr(mod.index, "embed", lambda *a, **k: [[1.0]])
    cleaned = []
    monkeypatch.setattr(mod, "cleanup", lambda profile, names: cleaned.append(names) or [])
    def fail(*args):
        raise RuntimeError("synthetic generation error")
    monkeypatch.setattr(mod.answer, "ask", fail)
    with pytest.raises(RuntimeError, match="generation error"):
        mod.run_question("example", {"base_url": "http://127.0.0.1:11437/v1", "model": "qwen2.5-coder:7b"})
    assert "qwen2.5-coder:7b" in cleaned[-1]

def test_saved_replay_has_partial_run_warning(capsys):
    load("show_doc_qa").main()
    text = capsys.readouterr().out
    assert "incomplete run" in text and "d01" in text and "d02" in text


def test_interactive_cleanup_failure_is_not_success(monkeypatch):
    mod = load("ask_local_docs")
    monkeypatch.setattr(mod, "preflight", lambda: {})
    monkeypatch.setattr(mod, "loaded", lambda profile: [])
    monkeypatch.setattr(mod.index, "Index", lambda path: type("FakeIndex", (), {"search": lambda self, *a, **k: []})())
    monkeypatch.setattr(mod.index, "embed", lambda *a, **k: [[1.0]])
    monkeypatch.setattr(mod.answer, "ask", lambda *a: ({"status": "ok"}, {}))
    monkeypatch.setattr(mod.cli, "show", lambda rec: None)
    monkeypatch.setattr(mod, "cleanup", lambda profile, names: ["synthetic unload failure"] if "qwen2.5-coder:7b" in names else [])
    with pytest.raises(RuntimeError, match="cleanup failed"):
        mod.run_question("example", {"base_url": "http://127.0.0.1:11437/v1", "model": "qwen2.5-coder:7b"})
