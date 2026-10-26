"""python -m doc_qa <command>

build    embed the knowledge base with local bge-m3 into knowledge/index/ (loads the embedding model)
ask      answer one question with citations, or say "not found" (loads bge-m3, then Qwen)
freeze   write an evaluation contract: hashes of corpus, index, questions, code, prompt, both model digests
eval     answer every question of a split under a frozen contract and score it (refuses changed inputs or a re-run)

Every command that loads a model first checks host resources (qwen_ops.resources.require) and refuses when they fail.
Model servers are reached on 127.0.0.1 only; nothing here uses the network.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

from qwen_ops import resources
from regression_triage import backend

from . import answer, evaluate, index

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge"
INDEX = KB / "index"
EV = ROOT / "evidence" / "doc-qa"
PROFILE = ROOT / "deploy" / "backends" / "ollama-r2.json"
CODE = ["doc_qa/__init__.py", "doc_qa/corpus.py", "doc_qa/index.py", "doc_qa/answer.py", "doc_qa/evaluate.py", "doc_qa/__main__.py",
        "qwen_agent/client.py", "qwen_agent/policy.py", "regression_triage/backend.py", "regression_triage/model.py", "qwen_ops/resources.py"]
K = 6


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def unload(profile, model, embedding=False):
    """Free the model from VRAM and host memory right away instead of waiting for keep_alive."""
    path, body = ("/api/embed", {"model": model, "input": [], "keep_alive": 0}) if embedding else ("/api/generate", {"model": model, "keep_alive": 0})
    req = urllib.request.Request(index.origin(profile["base_url"]) + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    index.OPENER.open(req, timeout=60).read()


def show(rec):
    s = rec["shown"]
    print(s["answer"])
    for n, c in enumerate(s["citations"], 1):
        print(f"  [{n}] {c['file']}:{c['lines'][0]}-{c['lines'][1]}  ({c['section']})\n      \"{c['quote'][:160]}\"")
    if rec.get("problems"):
        print("  (" + "; ".join(rec["problems"]) + ")")


def cmd_build(args):
    profile = backend.load(args.backend)
    resources.require(vram_needed_mb=1500)
    meta = index.build(ROOT, INDEX, profile["base_url"])
    unload(profile, index.EMBED_MODEL, embedding=True)
    print(json.dumps(meta, indent=1))


def cmd_ask(args):
    profile = backend.load(args.backend)
    resources.require()
    idx = index.Index(INDEX)
    hits = idx.search(args.question, index.embed([args.question], profile["base_url"])[0], k=K)
    rec, raw = answer.ask(args.question, hits, profile)
    show(rec)
    if args.out:
        write(args.out, {"record": rec, "raw": raw})


def cmd_freeze(args):
    out = EV / "contract" / f"{args.version}.json"
    if out.exists():
        raise SystemExit(f"{out} exists; contracts are immutable")
    if subprocess.run(["git", "status", "--porcelain", "--", *CODE, "knowledge"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        raise SystemExit("commit the doc-QA code, corpus, index and questions first")
    profile = backend.load(args.backend)
    splits = {p.stem: {"file": p.relative_to(ROOT).as_posix(), "sha256": sha(p), "questions": sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())}
              for p in sorted((KB / "questions").glob("*.jsonl"))}
    contract = {"version": args.version, "frozen_utc": now(), "note": args.note,
                "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                "corpus_manifest_sha256": sha(KB / "MANIFEST.json"), "index": {p.name: sha(p) for p in sorted(INDEX.iterdir())},
                "splits": splits, "code_sha256": {rel: sha(ROOT / rel) for rel in CODE},
                "prompt_version": answer.PROMPT_VERSION, "prompt_sha256": answer.prompt_sha256(), "k": K,
                "backend": profile, "backend_sha256": backend.sha256(profile), "qwen_identity": backend.identity(profile),
                "embed_model": index.EMBED_MODEL, "embed_model_digest": index.model_digest(profile["base_url"])}
    write(out, contract)
    print(out, {k: v["questions"] for k, v in splits.items()})


def check(contract, split):
    problems = [f"{rel} changed" for rel, d in contract["code_sha256"].items() if sha(ROOT / rel) != d]
    problems += [f"index/{n} changed" for n, d in contract["index"].items() if sha(INDEX / n) != d]
    if sha(KB / "MANIFEST.json") != contract["corpus_manifest_sha256"]:
        problems.append("corpus manifest changed")
    s = contract["splits"].get(split)
    if not s:
        problems.append(f"split {split} is not in the contract")
    elif sha(ROOT / s["file"]) != s["sha256"]:
        problems.append(f"{s['file']} changed")
    if answer.prompt_sha256() != contract["prompt_sha256"]:
        problems.append("prompt or schema changed")
    profile = contract["backend"]
    problems += backend.identity_problems(profile, backend.identity(profile))
    if index.model_digest(profile["base_url"]) != contract["embed_model_digest"]:
        problems.append("embedding model digest changed")
    return problems


def cmd_eval(args):
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    problems = check(contract, args.split)
    if problems:
        raise SystemExit("refusing to run: " + "; ".join(problems))
    out = EV / "results" / contract["version"] / args.split
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} already has results; a split is evaluated once per contract version")
    profile = contract["backend"]
    pre = resources.require()
    qs = [json.loads(line) for line in (ROOT / contract["splits"][args.split]["file"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    idx = index.Index(INDEX)
    vecs = index.embed([q["question"] for q in qs], profile["base_url"])  # all questions at once: one embedding-model load
    unload(profile, index.EMBED_MODEL, embedding=True)
    rows, aborted = [], None
    for q, v in zip(qs, vecs):
        mem = resources.memory()
        if resources.must_abort(mem):
            aborted = {"at_utc": now(), "before": q["id"], "memory": mem}
            break
        rec, raw = answer.ask(q["question"], idx.search(q["question"], v, k=contract["k"]), profile)
        row = evaluate.score(rec, q)
        write(out / f"{q['id']}.json", {"question": q, "record": rec, "score": row})
        if raw is not None:
            write(out / f"{q['id']}.model-response.json", raw)
        rows.append(row)
        print(q["id"], rec["status"], "found" if rec["shown"]["found"] else "not found", "correct" if row.get("correct") else "", flush=True)
    if args.unload:
        unload(profile, profile["model"])
    write(out / "metrics.json", {"contract": contract["version"], "split": args.split, "finished_utc": now(), "preflight": pre, "aborted": aborted,
                                 **evaluate.aggregate(rows)})
    print(json.dumps(evaluate.aggregate(rows), indent=1, ensure_ascii=False))
    return 1 if aborted else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="doc_qa")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    a = sub.add_parser("ask"); a.add_argument("question"); a.add_argument("--out")
    f = sub.add_parser("freeze"); f.add_argument("version"); f.add_argument("--note", default="")
    e = sub.add_parser("eval"); e.add_argument("--contract", required=True); e.add_argument("--split", required=True); e.add_argument("--unload", action="store_true")
    for sp in (b, a, f, e):
        sp.add_argument("--backend", default=str(PROFILE))
    args = p.parse_args(argv)
    try:
        return {"build": cmd_build, "ask": cmd_ask, "freeze": cmd_freeze, "eval": cmd_eval}[args.cmd](args) or 0
    except resources.ResourceError as exc:
        print(exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
