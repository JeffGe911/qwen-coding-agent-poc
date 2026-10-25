"""Development run on the dev split only: the current prompt against the local model, scored for rules, qwen and hybrid.

Not an evaluation (no contract): it exists so that prompt and guard changes are tried on dev, in the open, before a
contract is frozen. It refuses any other split. Every try keeps its raw responses and scores under
evidence/regression-triage/dev-iterations/<name>/, so the record shows what was tried before freezing.
Usage: python scripts/dev_try.py <name> [--backend deploy/backends/ollama-r2.json]
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from regression_triage import backend, evaluate, hybrid, logio, model, rules  # noqa: E402

EV = ROOT / "evidence" / "regression-triage"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("--backend", default=str(ROOT / "deploy" / "backends" / "ollama-r2.json"))
    args = p.parse_args()
    out = EV / "dev-iterations" / args.name
    if out.exists():
        raise SystemExit(f"{out} exists; use a new name")
    out.mkdir(parents=True)
    profile = backend.load(args.backend)
    manifest = json.loads((EV / "dataset" / "dev-manifest.json").read_text(encoding="utf-8"))
    assert manifest["split"] == "dev"
    totals = {e: {"tests": 0, "correct": 0, "false_release": 0, "cites": 0, "valid": 0} for e in ("rules", "qwen", "hybrid")}
    for s in manifest["samples"]:
        log = logio.read_log(s["file"], EV)
        gold = json.loads((EV / "gold" / "dev" / f"{s['sample_id']}.json").read_text(encoding="utf-8"))
        call, raw = model.triage(log, profile)
        preds = {"rules": rules.triage(log), "qwen": call.get("triage"), "hybrid": hybrid.combine(rules.triage(log), call.get("triage"), log)}
        rec = {"sample_id": s["sample_id"], "prompt_version": model.PROMPT_VERSION, "call": {k: v for k, v in call.items() if k != "triage"}, "scores": {}}
        for e, pred in preds.items():
            sc = evaluate.score_sample(pred or {"tests": []}, gold, log)
            rec["scores"][e] = sc
            tot = totals[e]
            tot["tests"] += len(sc["tests"])
            tot["correct"] += sum(t["category_ok"] for t in sc["tests"])
            tot["false_release"] += sum(t["gold"]["result"] != "pass" and t["pred"]["result"] == "pass" for t in sc["tests"])
            rejected = sum(len(t.get("rejected_citations", [])) for t in (pred or {}).get("tests", []))
            tot["cites"] += sum(t["citations"] for t in sc["tests"]) + rejected
            tot["valid"] += sum(t["citations_valid"] for t in sc["tests"])
        rec["hybrid"] = preds["hybrid"]
        (out / f"{s['sample_id']}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if raw is not None:
            (out / f"{s['sample_id']}.model-response.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(s["sample_id"], call["status"], {e: sum(t["category_ok"] for t in rec["scores"][e]["tests"]) for e in preds}, "/", len(gold["tests"]), flush=True)
    summary = {"name": args.name, "prompt_version": model.PROMPT_VERSION, "prompt_sha256": model.prompt_sha256(), "hybrid": hybrid.HYBRID_VERSION,
               "scoring": evaluate.SCORING_VERSION, "backend": profile["name"], "totals": totals}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(totals, indent=1))


if __name__ == "__main__":
    main()
