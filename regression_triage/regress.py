"""Regression runner: runs the tests of one manifest through the restricted executor and writes

    <out>/<run_id>/regression.log   tool output with "#RUN" annotation lines written by this runner
    <out>/<run_id>/run.json         commands, exit codes, elapsed time, timeouts, tool versions, source hashes

The runner records facts (exit code, wall-clock timeout) but no pass/fail verdict: deciding that is the triage's job.
Lines starting with "#RUN" are the runner's own; every other line is tool output exactly as produced.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import uuid

from . import sim


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Leading whitespace or a byte-order mark must not let a testbench line pass for a runner line (holdout h15 used an
# indented "#RUN"; logs from before this change only escaped column-1 forgeries).
IMITATION = re.compile(r"^[\s﻿]*#RUN")


def escape_tool_lines(tool_lines):
    """Prefix tool output that looks like a runner annotation with "#OUT ", so only the runner writes "#RUN" lines."""
    out = [("#OUT " + line) if IMITATION.match(line) else line for line in tool_lines]
    return out, sum(1 for line in tool_lines if IMITATION.match(line))


def run_regression(manifest_path, out_root, run_id=None):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    run_id = run_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{manifest['regression']}-{uuid.uuid4().hex[:6]}"
    out = Path(out_root) / run_id
    out.mkdir(parents=True)
    vers = sim.versions()
    lines = [f"#RUN regression={manifest['regression']} run_id={run_id} started_utc={now()} host_os={platform.system()}",
             f"#RUN tools iverilog=\"{' '.join(vers['iverilog'])}\" verilator=\"{' '.join(vers['verilator'])}\""]
    record = {"run_id": run_id, "regression": manifest["regression"], "manifest": Path(manifest_path).as_posix(),
              "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(), "started_utc": now(),
              "host": {"os": platform.platform(), "python": platform.python_version()}, "tools": vers, "eda_root": str(sim.eda_root()), "tests": []}
    for test in manifest["tests"]:
        sources = sim.check_test(test)
        work = sim.workdir(test["sources"])
        entry = {"test_id": test["test_id"], "defines": test.get("defines", []), "plusargs": test.get("plusargs", []),
                 "sources_sha256": {s: hashlib.sha256(p.read_bytes()).hexdigest() for s, p in zip(test["sources"], sources)}, "stages": []}
        try:
            for stage, argv in sim.commands(test, missing_tool=test.get("simulate_missing_tool", False)):
                shown = " ".join([Path(argv[0]).name, *argv[1:]])
                lines.append(f"#RUN test={test['test_id']} stage={stage} cmd={shown}")
                r = sim.execute(argv, work, float(test.get("timeout_s", 10)))
                tool_lines, escaped = escape_tool_lines(r["output"].splitlines())
                lines.extend(tool_lines)
                r["escaped_annotation_lines"] = escaped
                if r.get("tool_error"):
                    lines.append(f"#RUN test={test['test_id']} stage={stage} tool_error=\"{r['tool_error']}\" elapsed_s={r['elapsed_s']}")
                else:
                    lines.append(f"#RUN test={test['test_id']} stage={stage} exit={r['exit_code']} elapsed_s={r['elapsed_s']} "
                                 f"timed_out={str(r['timed_out']).lower()} output_truncated={str(r['output_truncated']).lower()}")
                entry["stages"].append({"stage": stage, "cmd": shown, **{k: v for k, v in r.items() if k != "output"}, "output_lines": len(r["output"].splitlines())})
                if r.get("tool_error") or r["exit_code"] != 0 or r["timed_out"]:
                    break  # a failed compile leaves nothing to run
        finally:
            shutil.rmtree(work, ignore_errors=True)
        record["tests"].append(entry)
    lines.append(f"#RUN regression={manifest['regression']} end tests={len(manifest['tests'])} finished_utc={now()}")
    record["finished_utc"] = now()
    (out / "regression.log").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (out / "run.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return out
