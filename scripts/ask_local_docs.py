"""One local document question, conservative preflight and cleanup; no changes to frozen qa-v1."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from doc_qa import __main__ as cli, answer, index
from qwen_ops import resources
from regression_triage import backend

LIMITS = {**resources.THRESHOLDS, "min_available_mb": 8192, "min_commit_headroom_mb": 10240}

def preflight():
    mem, gpu, ac = resources.memory(), resources.gpu(), resources.ac_power()
    problems = resources.problems(mem, gpu, ac, t=LIMITS)
    if problems:
        raise resources.ResourceError("not loading a model: " + "; ".join(problems))
    return {"memory": mem, "gpu": gpu, "ac_power": ac}

def loaded(profile):
    with index.OPENER.open(index.origin(profile["base_url"]) + "/api/ps", timeout=10) as response:
        return [m.get("name") or m.get("model") for m in json.load(response).get("models", [])]

def cleanup(profile, names):
    errors = []
    try:
        present = loaded(profile)
        for name in present:
            if name in names:
                try:
                    cli.unload(profile, name, embedding=name.startswith("bge-m3"))
                except Exception as exc:
                    errors.append(str(exc))
    except Exception as exc:
        errors.append(str(exc))
    return errors

def run_question(question, profile, out=None):
    pre = preflight()
    if loaded(profile):
        raise resources.ResourceError("model server already has a resident model; leave it unchanged and retry after it is idle")
    own = {profile["model"], index.EMBED_MODEL, index.EMBED_MODEL + ":latest"}
    try:
        idx = index.Index(ROOT / "knowledge/index")
        vector = index.embed([question], profile["base_url"])[0]
        errors = cleanup(profile, {index.EMBED_MODEL, index.EMBED_MODEL + ":latest"})
        if errors:
            raise RuntimeError("embedding cleanup failed: " + "; ".join(errors))
        preflight()
        hits = idx.search(question, vector, k=cli.K)
        rec, raw = answer.ask(question, hits, profile)
        if out:
            cli.write(out, {"preflight": pre, "record": rec, "raw": raw})
        cli.show(rec)
        return 0 if rec["status"] == "ok" else 1
    finally:
        errors = cleanup(profile, own)
        if errors:
            raise RuntimeError("model cleanup failed: " + "; ".join(errors))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("question")
    p.add_argument("--out")
    p.add_argument("--backend", default=str(ROOT / "deploy/backends/ollama-r2.json"))
    args = p.parse_args()
    try:
        return run_question(args.question, backend.load(args.backend), args.out)
    except (resources.ResourceError, OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 3

if __name__ == "__main__":
    sys.exit(main())
