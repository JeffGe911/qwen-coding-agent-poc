"""python -m qwen_ops <command>

health    layered health check (exit code = failing layer, see health.EXIT)
monitor   periodic sampler with alerts
capacity  concurrency + long-context probe against the running server
gate      regression gate for one model
logscan   problems in the Ollama server log that HTTP checks cannot see (context shift, CPU offload, GPU errors, 5xx)
release   snapshot | activate | rollback | verify | show
validate  one serving configuration against the frozen agent tasks; writes evidence/context-validation/<label>/

--service compose drives a Linux Docker Compose deployment (prepared, not exercised on this host).
"""
import argparse
import json
from pathlib import Path
import sys

from . import capacity, gate, monitor, ollama_log, release
from .health import EXIT, check
from .service import ComposeService, OllamaWindows, runtime_dir

ROOT = Path(__file__).resolve().parents[1]


def dump(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def service_args(sp, model_default="qwen2.5-coder:7b"):
    sp.add_argument("--service", choices=["ollama-windows", "compose"], default="ollama-windows")
    sp.add_argument("--port", type=int, default=11437, help="Ollama port (ollama-windows)")
    sp.add_argument("--base-url", help="OpenAI-compatible base URL; default http://127.0.0.1:<port>/v1")
    sp.add_argument("--model", default=model_default)
    sp.add_argument("--context", type=int, default=4096, help="settings of a release snapshot (--service ollama-windows)")
    sp.add_argument("--parallel", type=int, default=2)
    sp.add_argument("--max-queue", type=int, default=512)
    sp.add_argument("--compose-file", type=Path, default=ROOT / "deploy" / "compose.vllm.yaml")
    sp.add_argument("--env-file", type=Path, default=ROOT / "deploy" / ".env")
    sp.add_argument("--compose-service", default="inference")
    sp.add_argument("--out", type=Path, help="also write the JSON result here")


def make_service(args):
    if args.service == "compose":
        return ComposeService(args.compose_file, args.env_file, args.compose_service, args.base_url or "http://127.0.0.1:11436/v1")
    svc = OllamaWindows(args.port, args.context, args.parallel, args.max_queue)
    if args.base_url:
        svc.base_url = args.base_url
    return svc


def main(argv=None):
    p = argparse.ArgumentParser(prog="qwen_ops")
    sub = p.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("health"); service_args(h)
    h.add_argument("--no-golden", action="store_true"); h.add_argument("--api-timeout", type=float, default=5); h.add_argument("--model-timeout", type=float, default=90)
    m = sub.add_parser("monitor"); service_args(m)
    m.add_argument("--log", type=Path, required=True); m.add_argument("--interval", type=float, default=10); m.add_argument("--duration", type=float, default=60)
    c = sub.add_parser("capacity"); service_args(c)
    c.add_argument("--levels", default="1,2,4,8"); c.add_argument("--count", type=int, default=8); c.add_argument("--max-tokens", type=int, default=128)
    c.add_argument("--long-tokens", default="")
    g = sub.add_parser("gate"); service_args(g)
    s = sub.add_parser("logscan"); service_args(s)
    s.add_argument("--record", type=Path, help="launch record (evidence/serving/ollama-launch-*.json) of the launch to scan; default: newest for --port")
    s.add_argument("--log", type=Path, help="scan this saved .err.log copy instead (its .out.log next to it is used if present)")
    r = sub.add_parser("release"); service_args(r)
    r.add_argument("action", choices=["adopt", "snapshot", "activate", "rollback", "verify", "show"]); r.add_argument("--name"); r.add_argument("--note", default="")
    r.add_argument("--no-auto-rollback", action="store_true")
    r.add_argument("--max-tokens", type=int, help="agent output budget recorded in the manifest (default 1600)")
    v = sub.add_parser("validate")
    v.add_argument("--label", required=True); v.add_argument("--context", type=int, required=True); v.add_argument("--parallel", type=int, required=True)
    v.add_argument("--max-queue", type=int, default=512); v.add_argument("--max-tokens", type=int, default=1600); v.add_argument("--port", type=int, default=11437)
    v.add_argument("--no-tasks", action="store_true", help="service layer only (e.g. to verify a restore)"); v.add_argument("--note", default="")
    v.add_argument("--tasks", default="report_pass_rate,chip_final_yield", help="frozen tasks to run, comma separated")
    args = p.parse_args(argv)

    if args.cmd == "validate":
        from . import validate
        tasks = () if args.no_tasks else tuple(t for t in args.tasks.split(",") if t)
        doc = validate.run(args.label, args.context, args.parallel, args.max_queue, args.max_tokens, tasks,
                           args.port, args.note)
        gen = {t: {"status": g.get("status"), "error": (g.get("error") or "")[:200], "digest": g.get("approval_digest")} for t, g in doc["generation"].items()}
        dump({"label": doc["label"], "service": {k: doc["service"][k] for k in ("status", "ok", "residency", "effective")}, "generation": gen})
        return 0 if doc["service"]["ok"] else 1

    svc = make_service(args)
    ollama = args.service == "ollama-windows"
    code = 0
    if args.cmd == "health":
        res = check(svc.base_url, args.model, pid=svc.pid(), api_timeout=args.api_timeout, model_timeout=args.model_timeout, golden=not args.no_golden,
                    disk_path=runtime_dir() if ollama else ROOT, ollama=ollama)
        code = EXIT[res["status"]]
    elif args.cmd == "monitor":
        res = monitor.run(svc.base_url, args.model, args.log, ROOT, svc.pid, args.interval, args.duration, ollama=ollama,
                          launch_fn=svc.launch_record if ollama else None)
    elif args.cmd == "capacity":
        longs = [int(x) for x in args.long_tokens.split(",") if x]
        res = capacity.run(svc.base_url, args.model, [int(x) for x in args.levels.split(",")], args.count, args.max_tokens, longs)
    elif args.cmd == "gate":
        res = gate.run(svc.base_url, args.model, pid=svc.pid(), ollama=ollama)
        code = 0 if res["passed"] else 1
    elif args.cmd == "logscan":
        if args.log:
            rec = {"stderr_log": str(args.log)}
        elif args.record:
            rec = json.loads(args.record.read_text(encoding="utf-8-sig"))
        else:
            rec = svc.launch_record() if ollama else None
        if not rec:
            raise SystemExit("no launch record for this port (logscan reads the Ollama logs written by scripts/start_ollama.ps1)")
        res = ollama_log.scan(rec)
        counts = res["stderr"]["counts"]
        code = 1 if any(counts[k] for k in ("context_shift", "truncated", "cpu_offload", "gpu_error", "runner_exit", "gpu_warning")) else 0
    else:
        if args.action in ("snapshot", "adopt") and not args.name:
            raise SystemExit("--name is required")
        if args.action == "snapshot":
            res = release.snapshot(args.name, svc, args.model, args.note, max_tokens=args.max_tokens)
        elif args.action == "adopt":
            res = release.adopt(args.name, svc, args.model, args.note)
        elif args.action == "activate":
            res = release.activate(args.name, auto_rollback=not args.no_auto_rollback)
            code = 0 if res.get("active") == args.name and res["gate"]["passed"] else 1
        elif args.action == "rollback":
            res = release.rollback()
            code = 0 if res["gate"]["passed"] else 1
        elif args.action == "verify":
            name = args.name or release.active_name()
            manifest = release.load(name)
            res = {"name": name, "problems": release.verify_pins(manifest, release.service_for(manifest))}
            code = 0 if not res["problems"] else 1
        else:
            name = release.active_name()
            res = {"active": name, "manifest": release.load(name) if name else None, "previous": release.previous_release(name) if name else None}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if args.cmd == "monitor":
        dump(res[-6:])
    elif args.cmd == "capacity":
        dump({**{k: v for k, v in res.items() if k != "concurrency"}, "concurrency": [{k: v for k, v in r.items() if k != "per_request"} for r in res["concurrency"]]})
    else:
        dump(res)
    return code


if __name__ == "__main__":
    sys.exit(main())
