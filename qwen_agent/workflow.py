from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import time
import uuid

from .client import DEFAULT_MAX_TOKENS, Client, prompt_sha256
from .generation import check_profile, format_sha256, parse
from .policy import POLICY_REVISION, PolicyError, digest, validate
from .runner import ROOT, execute

TASKS = Path(__file__).resolve().parent / "tasks"
FILES = ("solution.py", "test_visible.py", "test_holdout.py")
TERMINAL = {"succeeded", "failed", "rejected", "policy_blocked", "model_error", "infra_error"}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contract(task_path, generation=None):
    """Everything that defines what the model saw and how code is judged.

    Stored in state["config"], so it is part of every approval digest: a reviewer
    approves code against this exact prompt, policy and frozen test snapshot.
    With a generation profile (contract revision 2+) the prompt digest is that of its output format.
    """
    return {
        "prompt_sha256": format_sha256(generation["format"]) if generation else prompt_sha256(),
        "policy_revision": POLICY_REVISION,
        "policy_sha256": sha256_file(Path(__file__).resolve().parent / "policy.py"),
        "task_files_sha256": {name: sha256_file(task_path / name) for name in FILES + ("task.json",)},
    }


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def event(run, kind, **data):
    with (run / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": now(), "type": kind, **data}, ensure_ascii=False) + "\n")


@contextmanager
def lock(run):
    path = run / ".lock"
    try:
        stream = path.open("x")
    except FileExistsError as exc:
        raise ValueError("Run is locked; inspect for an interrupted process before manually removing .lock") from exc
    try:
        stream.write(now())
        stream.close()
        yield
    finally:
        path.unlink(missing_ok=True)


def snapshot(workspace):
    entries = list(workspace.iterdir())
    if any(p.is_symlink() or not p.is_file() for p in entries) or {p.name for p in entries} != set(FILES):
        raise ValueError("Workspace must contain exactly the three expected regular files")
    return {name: (workspace / name).read_text(encoding="utf-8") for name in FILES}


def binding(state, proposal, files):
    return digest({"run_id": state["run_id"], "task": state["task"], "config": state["config"], "attempt": proposal["attempt"], "code": proposal["code"], "explanation": proposal["explanation"], "workspace": files})


def earlier_proposals(run, state):
    """Code of every earlier proposal in this run, keyed by attempt number."""
    codes = {}
    for item in state["attempts"]:
        path = run / f"attempt-{item['attempt']}" / "proposal.json"
        if path.exists():
            codes[item["attempt"]] = (read_json(path)["code"].strip(), item["status"])
    return codes


def propose(run, state, client=None):
    """Ask for a proposal; after a policy block, re-ask with feedback while budget remains.

    Never executes anything: every proposal that passes validation stops at
    awaiting_approval for a human decision.
    """
    config = state["config"]
    client = client or Client(config["base_url"], config["model"])
    while True:
        state = propose_once(run, state, client)
        if state["status"] != "policy_blocked" or state.get("stop_reason"):
            return state
        if len(state["attempts"]) >= config["max_attempts"]:
            state["stop_reason"] = "proposal_budget_exhausted"
            write_json(run / "state.json", state)
            return state
        error = state["attempts"][-1].get("error", "invalid output")
        state["feedback"] += "\nPrevious proposal was rejected by the code policy before execution: " + error + ". Stay within the allowed subset."
        event(run, "auto_repropose", after_attempt=len(state["attempts"]), reason=error)


def propose_once(run, state, client):
    files = snapshot(run / "workspace")
    started = time.monotonic()
    attempt = len(state["attempts"]) + 1
    folder = run / f"attempt-{attempt}"
    folder.mkdir()
    state["status"] = "generating"
    write_json(run / "state.json", state)
    try:
        # Runs created before max_tokens was recorded used the default; the argument is only passed when it differs.
        budget = {"max_tokens": state["config"]["max_tokens"]} if state["config"].get("max_tokens", DEFAULT_MAX_TOKENS) != DEFAULT_MAX_TOKENS else {}
        generation = state["config"].get("generation")
        if generation:
            budget = {"profile": generation}
        response = client.propose(state["task"], files["solution.py"], files["test_visible.py"], state["feedback"], **budget)
        write_json(folder / "model-response.json", response)
        choice = response["choices"][0]
        usage = response.get("usage") or {}
        # Both checks are reported together: an output cut off by max_tokens and a context overflow are different problems.
        problems = [p for p in (output_problem(choice.get("finish_reason"), usage, state["config"].get("max_tokens") or DEFAULT_MAX_TOKENS),
                                context_problem(usage, state["config"].get("context_tokens")),
                                server_mismatch(client, state["config"].get("context_tokens"))) if p]
        if problems:
            raise ValueError("; ".join(problems))
        proposal, format_facts = parse(generation["format"] if generation else "json_v1", choice["message"]["content"])
        proposal["attempt"] = attempt
        proposal["digest"] = binding(state, proposal, files)
        write_json(folder / "proposal.json", proposal)
        diff = "".join(difflib.unified_diff(files["solution.py"].splitlines(True), proposal["code"].splitlines(True), fromfile="before/solution.py", tofile="after/solution.py"))
        (folder / "diff.txt").write_text(diff, encoding="utf-8")
        item = {"attempt": attempt, "digest": proposal["digest"], "proposed_at": now(), "generation_seconds": round(time.monotonic() - started, 3), "usage": response.get("usage"), "status": "awaiting_approval"}
        if generation:
            item["format_facts"] = format_facts
        code = proposal["code"].strip()
        repeat = next((n for n, (old, _) in earlier_proposals(run, state).items() if old == code), None)
        if code == files["solution.py"].strip():
            item.update(status="no_change", error="Model returned the current solution.py unchanged; no execution or approval requested")
            state["status"] = "failed"
            state["stop_reason"] = "no_change"
        elif repeat is not None:
            # Same code as an earlier proposal: stop instead of looping. The run keeps the
            # category of the earlier outcome (blocked code stays blocked; failed stays failed).
            item.update(status="duplicate", error=f"Model repeated the code of attempt {repeat}; stopped to avoid a loop")
            state["status"] = "policy_blocked" if earlier_proposals(run, state)[repeat][1] == "policy_blocked" else "failed"
            state["stop_reason"] = "duplicate_proposal"
        else:
            try:
                validate(proposal["code"])
            except PolicyError as exc:
                item.update(status="policy_blocked", error=str(exc))
            state["status"] = item["status"]
        state["attempts"].append(item)
        event(run, item["status"], attempt=attempt, digest=proposal["digest"], error=item.get("error"))
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        state["status"] = "model_error"
        state["error"] = f"{type(exc).__name__}: {exc}"
        state["attempts"].append({"attempt": attempt, "status": "model_error", "generation_seconds": round(time.monotonic() - started, 3), "error": state["error"]})
        event(run, "model_error", error=state["error"])
    write_json(run / "state.json", state)
    return state


def output_problem(finish_reason, usage, max_tokens):
    """The output stopped for another reason than the model finishing (usually the max_tokens budget)."""
    if finish_reason in ("stop", None):
        return None
    return (f"Output incomplete: finish_reason={finish_reason} after {usage.get('completion_tokens')} completion tokens "
            f"(output budget max_tokens={max_tokens})")


def context_problem(usage, context_tokens):
    """Output generated past the server's per-request context window.

    Ollama/llama.cpp then shifts the context (drops part of the prompt) and still reports
    finish_reason=stop, so the code was written without the full requirement in view.
    """
    if not context_tokens or not usage:
        return None
    used = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    if used >= context_tokens:
        return (f"Context overflow: prompt + output used {used} tokens, reaching the server context window of {context_tokens}; "
                "the server may have discarded part of the prompt (context shift). Increase the server context and start a new run")
    return None


def server_mismatch(client, context_tokens):
    """A run records the server context it expects; a proposal generated by a server running another context does not count."""
    actual = getattr(client, "server_context", lambda: None)() if context_tokens else None
    if actual and actual != context_tokens:
        return f"Server context mismatch: the server ran with {actual} tokens per request, this run is configured for {context_tokens}"
    return None


def check_context(usage, context_tokens):
    problem = context_problem(usage, context_tokens)
    if problem:
        raise ValueError(problem)


def start(task_id, runs, base_url, model, sandbox="docker", max_attempts=3, client=None, context_tokens=None, max_tokens=None, generation=None,
          contract_revision=None):
    if task_id not in {p.name for p in TASKS.iterdir() if p.is_dir()}:
        raise ValueError("Unknown bundled task")
    if not 1 <= max_attempts <= 3:
        raise ValueError("max-attempts must be 1..3")
    Client(base_url, model)  # Validate the endpoint before doing any work.
    task_path = TASKS / task_id
    if generation:
        check_profile(generation)
        max_tokens = generation["max_tokens"]
    frozen = contract(task_path, generation)
    run = Path(runs).resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + task_id + "-" + uuid.uuid4().hex[:8])
    workspace = run / "workspace"
    workspace.mkdir(parents=True)
    for name in FILES:
        (workspace / name).write_text((task_path / name).read_text(encoding="utf-8"), encoding="utf-8")
    config = {"base_url": base_url, "model": model, "sandbox": sandbox, "max_attempts": max_attempts, "timeout_seconds": 20, "contract": frozen}
    if context_tokens:
        config["context_tokens"] = context_tokens  # server window per request; see context_problem
    config["max_tokens"] = max_tokens or DEFAULT_MAX_TOKENS  # output budget, recorded so it is part of the approval digest
    if generation:
        config["generation"] = generation  # format, transport and every sampling value, recorded before any model call
    if contract_revision:
        config["contract_revision"] = contract_revision
    state = {"run_id": run.name, "created_at": now(), "task": read_json(task_path / "task.json"), "config": config, "attempts": [], "status": "baseline"}
    write_json(run / "state.json", state)
    event(run, "created", task=task_id, sandbox=sandbox, model=model, contract=frozen)
    with lock(run):
        try:
            baseline = execute(workspace, sandbox)
            write_json(run / "baseline.json", baseline)
            state["baseline"] = baseline
            if baseline["exit_code"] != 1 or baseline.get("tests", 0) == 0 or baseline.get("errors", 0):
                raise RuntimeError("Expected a collected, failing baseline; task/runner needs inspection")
            # Holdout results remain evaluation-only; the model sees visible-test feedback.
            state["feedback"] = visible_feedback(baseline)
            propose(run, state, client)
        except (RuntimeError, OSError, ValueError) as exc:
            state["status"] = "infra_error"
            state["error"] = str(exc)
            event(run, "infra_error", error=str(exc))
            write_json(run / "state.json", state)
    return run, state


def retry(run, client=None):
    """Retry a blocked/malformed proposal, or close an already pending no-op."""
    run = Path(run).resolve()
    with lock(run):
        state = read_json(run / "state.json")
        if state["status"] == "awaiting_approval":
            item = state["attempts"][-1]
            proposal = read_json(run / f"attempt-{item['attempt']}" / "proposal.json")
            files = snapshot(run / "workspace")
            if binding(state, proposal, files) != item["digest"] or proposal["code"].strip() != files["solution.py"].strip():
                raise ValueError("Changed proposals require a human decision")
            item["status"] = "no_change"
            state["status"] = "failed"
            event(run, "no_change", attempt=item["attempt"])
            write_json(run / "state.json", state)
            return state
        if state["status"] not in {"policy_blocked", "model_error"}:
            raise ValueError("Only blocked/model-error proposals can be retried")
        if state.get("stop_reason"):
            raise ValueError(f"Run stopped ({state['stop_reason']}); start a new run instead of retrying")
        if len(state["attempts"]) >= state["config"]["max_attempts"]:
            raise ValueError("Proposal budget exhausted")
        last = state["attempts"][-1]
        state["feedback"] += "\nPrevious proposal rejected before execution: " + last.get("error", "invalid output") + ". Stay within the allowed subset and return the required JSON."
        return propose(run, state, client)


def decide(run, decision, approved_digest, reviewer, client=None):
    run = Path(run).resolve()
    if not reviewer.strip():
        raise ValueError("A human reviewer name is required")
    with lock(run):
        state = read_json(run / "state.json")
        if state["status"] != "awaiting_approval":
            raise ValueError("Run is not awaiting approval; completed/rejected decisions cannot be replayed")
        item = state["attempts"][-1]
        proposal = read_json(run / f"attempt-{item['attempt']}" / "proposal.json")
        files = snapshot(run / "workspace")
        actual = binding(state, proposal, files)
        if approved_digest != item["digest"] or approved_digest != proposal["digest"] or approved_digest != actual:
            raise ValueError("Approval digest mismatch: proposal/workspace/config changed. Do not execute")
        if decision not in {"approve", "reject"}:
            raise ValueError("Decision must be approve or reject")
        item["reviewer"] = reviewer
        item["reviewed_at"] = now()
        if item.get("proposed_at"):
            item["approval_wait_seconds"] = round((datetime.fromisoformat(item["reviewed_at"]) - datetime.fromisoformat(item["proposed_at"])).total_seconds(), 3)
        event(run, decision, reviewer=reviewer, digest=actual, attempt=item["attempt"])
        if decision == "reject":
            item["status"] = state["status"] = "rejected"
            write_json(run / "state.json", state)
            return state
        validate(proposal["code"])
        state["status"] = item["status"] = "executing"
        write_json(run / "state.json", state)
        # Reconstruct a fresh, minimal execution directory from the reviewed bytes.
        folder = run / f"attempt-{item['attempt']}"
        job = folder / "job"
        job.mkdir()
        for name in FILES:
            (job / name).write_text(proposal["code"] if name == "solution.py" else files[name], encoding="utf-8")
        try:
            result = execute(job, state["config"]["sandbox"], state["config"]["timeout_seconds"])
        except (RuntimeError, OSError, ValueError) as exc:
            item["status"] = state["status"] = "infra_error"
            state["error"] = str(exc)
            event(run, "infra_error", error=str(exc))
            write_json(run / "state.json", state)
            return state
        write_json(folder / "pytest.json", result)
        item["result"] = result
        success = result["exit_code"] == 0 and result.get("tests", 0) == state["baseline"]["tests"] and result.get("skipped", 0) == 0
        item["status"] = "passed" if success else "failed"
        event(run, "pytest_finished", attempt=item["attempt"], passed=success, exit_code=result["exit_code"])
        (run / "workspace" / "solution.py").write_text(proposal["code"], encoding="utf-8")
        if success:
            state["status"] = "succeeded"
        elif result["exit_code"] not in (0, 1, 2, -1):
            state["status"] = "infra_error"
            state["error"] = "pytest collection/internal error; inspect pytest.json"
        elif len(state["attempts"]) >= state["config"]["max_attempts"]:
            state["status"] = "failed"
            state["stop_reason"] = "proposal_budget_exhausted"
        else:
            # Only visible failures are fed back; omit holdout assertion text.
            state["feedback"] = visible_feedback(result)
            return propose(run, state, client)
        write_json(run / "state.json", state)
        return state


def visible_feedback(result):
    return "Visible test failures:\n" + result.get("visible_feedback", "Execution timed out or only holdout tests failed.") + "\nOther evaluation cases may also fail; follow the full requirement."

