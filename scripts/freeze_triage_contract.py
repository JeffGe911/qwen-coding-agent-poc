"""Freeze the regression-triage evaluation contract before any formal run.

Writes evidence/regression-triage/contract/<version>.json with the sample and gold hashes of both splits, the code
hashes of the rule baseline / model client / scorer, the prompt+schema hash, model and sampling settings, budgets and
metric definitions. `python -m regression_triage eval` refuses to run when anything differs. Refuses to overwrite.
Usage: python scripts/freeze_triage_contract.py <version> [--note TEXT]
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from regression_triage import backend, evaluate, hybrid, model, rules

EV = ROOT / "evidence" / "regression-triage"
# Everything on the request and scoring path, including the shared client: eval-v1/v2 hashed only the first five, so a
# change in qwen_agent/client.py (timeout, auth, URL checks) would have gone unnoticed.
CODE = ["regression_triage/rules.py", "regression_triage/model.py", "regression_triage/evaluate.py", "regression_triage/logio.py", "regression_triage/__main__.py",
        "regression_triage/backend.py", "regression_triage/hybrid.py", "qwen_agent/client.py", "qwen_agent/workflow.py", "qwen_agent/policy.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("version")
    p.add_argument("--note", default="")
    p.add_argument("--backend", default=str(ROOT / "deploy" / "backends" / "ollama-r2.json"), help="backend profile for the model engine")
    p.add_argument("--engines", choices=["rules", "rules,qwen", "rules,qwen,hybrid"], default="rules,qwen",
                   help="'rules' freezes without a model block (no server needed); the model then needs a later contract version")
    args = p.parse_args()
    out = EV / "contract" / f"{args.version}.json"
    if out.exists():
        raise SystemExit(f"{out} exists; contracts are immutable, use a new version")
    if subprocess.run(["git", "status", "--porcelain", "--", *CODE], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        raise SystemExit("commit the triage code first: a contract must point at a commit that contains exactly the hashed code")
    dataset = {}
    for split in ("dev", "holdout", "holdout2"):
        if not (EV / "dataset" / f"{split}-manifest.json").exists():
            continue
        manifest = json.loads((EV / "dataset" / f"{split}-manifest.json").read_text(encoding="utf-8"))
        rows = []
        for s in manifest["samples"]:
            gold = f"gold/{split}/{s['sample_id']}.json"
            if sha(EV / s["file"]) != s["sha256"]:
                raise SystemExit(f"{s['file']} no longer matches its manifest hash")
            rows.append({"sample_id": s["sample_id"], "kind": s["kind"], "file": s["file"], "sha256": s["sha256"], "gold": gold, "gold_sha256": sha(EV / gold)})
        dataset[split] = rows
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    qwen = None
    if "qwen" in args.engines:
        profile = backend.load(args.backend)
        served = backend.identity(profile)  # listing only; never loads a model
        problems = backend.identity_problems(profile, served)
        if problems:
            raise SystemExit("the running server does not match the backend profile: " + "; ".join(problems))
        qwen = {"backend_file": Path(args.backend).resolve().relative_to(ROOT).as_posix(), "backend": profile, "backend_sha256": backend.sha256(profile),
                "served_identity_at_freeze": served, "transport": "/v1/chat/completions with response_format json_schema",
                "release": (ROOT / "deploy" / "releases" / "ACTIVE").read_text(encoding="utf-8").strip() if profile["kind"] == "ollama" else None,
                "prompt_version": model.PROMPT_VERSION, "prompt_sha256": model.prompt_sha256()}
    contract = {
        "version": args.version, "frozen_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": args.note,
        "git_commit": commit, "code_uncommitted_changes": False, "engines": args.engines.split(","),
        "dataset": dataset, "dataset_counts": {k: {"samples": len(v), "real": sum(r["kind"] == "real" for r in v), "synthetic": sum(r["kind"] == "synthetic" for r in v)} for k, v in dataset.items()},
        "code_sha256": {rel: sha(ROOT / rel) for rel in CODE},
        "rules": {"version": rules.RULES_VERSION}, "scoring": evaluate.SCORING_VERSION,
        "hybrid": {"version": hybrid.HYBRID_VERSION} if "hybrid" in args.engines else None,
        "qwen": qwen,
        "split_policy": "dev may be used to develop rules and prompts. holdout is labelled independently and is run once per contract version and engine; "
                        "any rule or prompt change after looking at holdout results needs a new contract version and is not called blind.",
        "metrics": {"category_accuracy": "gold tests whose predicted category equals gold (missing tests count as wrong)",
                    "flagged_precision_recall": "tests with result fail or not_run",
                    "citation_valid_rate": "citations whose file is the log, line exists and quote is a substring of the line (>= 6 chars)",
                    "citation_relevant_rate": "valid citations that point at a gold evidence line of that test",
                    "unknown_rate": "predicted tests with category unknown / gold tests",
                    "invalid_output / request_failed": "model calls only", "seconds / tokens": "per request, model calls only"},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(out, contract["dataset_counts"], "code dirty:", contract["code_uncommitted_changes"])


if __name__ == "__main__":
    main()
