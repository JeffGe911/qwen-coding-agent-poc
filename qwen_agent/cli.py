import argparse
import json
from pathlib import Path
import sys

from .client import Client
from .report import generate
from .workflow import TASKS, decide, read_json, retry, start


def active_release_defaults():
    """Base URL, model and per-request context of the release in service (deploy/releases/ACTIVE), else the historical defaults."""
    releases = Path(__file__).resolve().parents[1] / "deploy" / "releases"
    try:
        name = (releases / "ACTIVE").read_text(encoding="utf-8").strip()
        manifest = json.loads((releases / f"{name}.json").read_text(encoding="utf-8"))
        return manifest["agent"]["base_url"], manifest["agent"]["model"], manifest["server"].get("context")
    except (OSError, ValueError, KeyError):
        return "http://127.0.0.1:11434/v1", "qwen2.5-coder:1.5b", None


def load_contract_arm(path, arm, task_id):
    """One arm of a versioned evaluation contract (qwen_agent/contracts/<task>/revN.json), checked against the frozen task files."""
    import hashlib
    raw = Path(path).read_bytes()
    doc = json.loads(raw)
    if doc["task"] != task_id:
        raise ValueError(f"contract {doc['id']} is for task {doc['task']}, not {task_id}")
    for name, expected in doc["task_files_sha256"].items():
        if hashlib.sha256((TASKS / task_id / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"task file {name} differs from contract {doc['id']}; refusing to run")
    if arm not in doc["arms"]:
        raise ValueError(f"contract {doc['id']} has no arm {arm!r}; arms: {sorted(doc['arms'])}")
    spec = doc["arms"][arm]
    revision = {"id": doc["id"], "revision": doc["revision"], "arm": arm, "changes_vs_rev1": spec["changes_vs_rev1"],
                "file": Path(path).as_posix(), "sha256": hashlib.sha256(raw).hexdigest()}
    return spec["model"], spec["generation"], doc["server"]["context_per_request"], revision


def show(run, state):
    print(f"Run: {run}\nStatus: {state['status']}")
    if state.get("error"):
        print("Error:", state["error"])
    if state["status"] == "awaiting_approval":
        item = state["attempts"][-1]
        folder = run / f"attempt-{item['attempt']}"
        print((folder / "diff.txt").read_text(encoding="utf-8"))
        print("Explanation:", read_json(folder / "proposal.json")["explanation"])
        print("Approval digest:", item["digest"])
        print(f'Human review: python -m qwen_agent decide "{run}" approve --digest {item["digest"]} --reviewer YOUR_NAME')


def interactive(run, state, reviewer):
    while state["status"] == "awaiting_approval":
        show(run, state)
        token = state["attempts"][-1]["digest"]
        try:
            answer = input(f"Type approve {token} or reject {token}; Enter leaves pending:\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nLeft pending; no execution.")
            return state
        if answer not in {"approve " + token, "reject " + token}:
            print("Left pending; no execution.")
            return state
        state = decide(run, answer.split()[0], token, reviewer)
    show(run, state)
    return state


def main():
    parser = argparse.ArgumentParser(description="Small local coding agent with manual approval; no auto-approve option")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    propose = commands.add_parser("start")
    demo = commands.add_parser("demo")
    default_url, default_model, default_context = active_release_defaults()
    for p in (doctor, propose, demo):
        p.add_argument("--base-url", default=default_url)
        p.add_argument("--model", default=default_model)
    task_ids = [p.name for p in TASKS.iterdir() if p.is_dir()]
    for p in (propose, demo):
        p.add_argument("--task", choices=task_ids + (["all"] if p is demo else []), required=True)
        p.add_argument("--runs", type=Path, default=Path("runs"))
        p.add_argument("--sandbox", choices=["docker", "restricted"], default="docker")
        p.add_argument("--max-attempts", type=int, default=3)
        p.add_argument("--context-tokens", type=int,
                       help="server context window per request; output reaching it is rejected (default: the active release's, when --base-url and --model are the release's)")
        p.add_argument("--max-tokens", type=int, help="output budget per proposal (default 1600); recorded in the run config")
    propose.add_argument("--contract", type=Path, help="versioned evaluation contract, e.g. qwen_agent/contracts/chip_final_yield/rev2.json")
    propose.add_argument("--arm", help="arm of --contract; its model, format and sampling replace --model/--max-tokens")
    demo.add_argument("--reviewer", required=True)
    review = commands.add_parser("show")
    review.add_argument("run", type=Path)
    retry_parser = commands.add_parser("retry")
    retry_parser.add_argument("run", type=Path)
    decision = commands.add_parser("decide")
    decision.add_argument("run", type=Path)
    decision.add_argument("decision", choices=["approve", "reject"])
    decision.add_argument("--digest", required=True)
    decision.add_argument("--reviewer", required=True)
    report = commands.add_parser("report")
    report.add_argument("--runs", type=Path, default=Path("runs"))
    report.add_argument("--output", type=Path, default=Path("evidence"))
    args = parser.parse_args()
    if getattr(args, "context_tokens", 1) is None and (args.base_url, args.model) == (default_url, default_model):
        args.context_tokens = default_context  # the release window only describes the release's own server
    try:
        if args.command == "doctor":
            models = Client(args.base_url, args.model).models()
            print(json.dumps(models, indent=2))
            if args.model not in [m["id"] for m in models.get("data", [])]:
                raise ValueError("Requested model is not loaded/available")
        elif args.command in {"start", "demo"}:
            selected = sorted(task_ids) if args.task == "all" else [args.task]
            failed = False
            extra = {}
            if getattr(args, "contract", None):
                if not args.arm or args.max_tokens:
                    raise ValueError("--contract needs --arm, and the arm fixes the output budget (no --max-tokens)")
                args.model, extra["generation"], window, extra["contract_revision"] = load_contract_arm(args.contract, args.arm, args.task)
                args.context_tokens = args.context_tokens or window
            for task_id in selected:
                run, state = start(task_id, args.runs, args.base_url, args.model, args.sandbox, args.max_attempts, context_tokens=args.context_tokens,
                                   max_tokens=args.max_tokens, **extra)
                if args.command == "demo":
                    state = interactive(run, state, args.reviewer)
                else:
                    show(run, state)
                failed |= state["status"] in {"infra_error", "model_error", "policy_blocked", "failed"}
            return int(failed)
        elif args.command == "show":
            show(args.run, read_json(args.run / "state.json"))
        elif args.command == "decide":
            state = decide(args.run, args.decision, args.digest, args.reviewer)
            show(args.run, state)
            if state["status"] in {"failed", "infra_error", "model_error", "policy_blocked"}:
                return 1
        elif args.command == "retry":
            state = retry(args.run)
            show(args.run, state)
            if state["status"] in {"failed", "infra_error", "model_error", "policy_blocked"}:
                return 1
        else:
            print(json.dumps(generate(args.runs, args.output), indent=2, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0

