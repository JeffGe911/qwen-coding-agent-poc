"""Restricted simulation executor.

Only three programs can run (iverilog, vvp, verilator in lint-only mode), with argument lists built here from
validated manifest fields; nothing comes from a model or a log. Sources must be regular .v/.sv files under hdl/ and
are copied into a fresh working directory, so tool output shows short relative paths. Each process has a wall-clock
limit, an output cap and (on Windows) a Job Object memory cap with kill-on-close. This is a resource and scope
limit for reviewed, fixed commands, not an OS security sandbox.
"""
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
HDL = ROOT / "hdl"
MAX_SOURCE_BYTES = 200_000
MAX_OUTPUT_BYTES = 1_000_000
MEMORY_LIMIT_MB = 512
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PLUSARG = re.compile(r"^\+[A-Za-z_][A-Za-z0-9_]{0,31}(=[A-Za-z0-9_.-]{0,32})?$")


def eda_root():
    """OSS CAD Suite folder ($QWEN_POC_EDA, else ../../work/tools/oss-cad-suite-20261024/oss-cad-suite)."""
    return Path(os.environ.get("QWEN_POC_EDA") or ROOT.parents[1] / "work" / "tools" / "oss-cad-suite-20261024" / "oss-cad-suite")


def tool(name):
    exe = {"iverilog": "iverilog", "vvp": "vvp", "verilator": "verilator_bin"}[name] + (".exe" if os.name == "nt" else "")
    return eda_root() / "bin" / exe


def check_source(rel):
    path = (ROOT / rel).resolve()
    if HDL.resolve() not in path.parents or path.suffix not in (".v", ".sv") or path.is_symlink() or not path.is_file():
        raise ValueError(f"source {rel} is not a .v/.sv file under hdl/")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError(f"source {rel} exceeds {MAX_SOURCE_BYTES} bytes")
    return path


def check_test(test):
    if not NAME.match(test["test_id"]) or not NAME.match(test["top"]):
        raise ValueError(f"bad test_id/top in {test}")
    for d in test.get("defines", []):
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,31}", d):
            raise ValueError(f"bad define {d!r}")
    for p in test.get("plusargs", []):
        if not PLUSARG.match(p):
            raise ValueError(f"bad plusarg {p!r}")
    if not 1 <= float(test.get("timeout_s", 10)) <= 60:
        raise ValueError("timeout_s must be 1..60")
    if test.get("kind", "sim") not in ("sim", "lint"):
        raise ValueError("kind must be sim or lint")
    return [check_source(s) for s in test["sources"]]


def commands(test, binary="sim.vvp", missing_tool=False):
    """(stage, argv) pairs for one test. argv[0] is a resolved tool path; a missing_tool test points at a name that does not exist."""
    defines = [f"-D{d}" for d in test.get("defines", [])]
    sources = list(test["sources"])
    pick = (lambda n: tool(n).with_name("iverilog-not-installed.exe")) if missing_tool else tool
    if test.get("kind", "sim") == "lint":
        return [("lint", [str(pick("verilator")), "--lint-only", "-Wall", "--top-module", test["top"], *defines, *sources])]
    return [("compile", [str(pick("iverilog")), "-g2012", "-o", binary, "-s", test["top"], *defines, *sources]),
            ("run", [str(pick("vvp")), "-n", binary, *test.get("plusargs", [])])]


class _Job:
    """Windows Job Object: memory cap per process, kill everything when the handle closes."""

    def __init__(self, memory_mb):
        k32 = ctypes.windll.kernel32
        self.k32 = k32
        self.handle = k32.CreateJobObjectW(None, None)

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", ctypes.c_uint32),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXT()
        # PROCESS_MEMORY 0x100 | KILL_ON_JOB_CLOSE 0x2000 | ACTIVE_PROCESS 0x8
        info.Basic.LimitFlags = 0x100 | 0x2000 | 0x8
        info.Basic.ActiveProcessLimit = 8  # iverilog -> cmd -> ivlpp, ivl
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
        self.info = info
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject failed")

    def adopt(self, popen):
        if not self.k32.AssignProcessToJobObject(self.handle, int(popen._handle)):
            raise OSError("AssignProcessToJobObject failed")
        ctypes.windll.ntdll.NtResumeProcess(int(popen._handle))  # started suspended, so nothing ran outside the job

    def terminate(self):
        """End every process in the job (the tool and anything it started, e.g. iverilog's ivlpp/ivl or a venv launcher's child)."""
        self.k32.TerminateJobObject(self.handle, 1)

    def close(self):
        self.k32.CloseHandle(self.handle)


def _limits():  # POSIX only; the Linux path is written but not exercised on this host
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_MB * 2**20,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES * 4,) * 2)
    os.setsid()


def execute(argv, cwd, timeout_s, memory_mb=MEMORY_LIMIT_MB):
    """Run one fixed command. Output (stdout+stderr, in order) goes to a file and is read back with a cap."""
    env = {"PATH": os.pathsep.join([str(eda_root() / "bin"), str(eda_root() / "lib")] + ([os.environ.get("SystemRoot", r"C:\Windows")] if os.name == "nt" else ["/usr/bin", "/bin"])),
           "TEMP": str(cwd), "TMP": str(cwd),
           # OSS CAD Suite's environment script does not set this; without it Verilator looks in a compiled-in /yosyshq path.
           "VERILATOR_ROOT": str(eda_root() / "share" / "verilator")}
    if os.name == "nt":
        env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
        # iverilog starts its preprocessor and compiler through popen(), which needs cmd.exe via COMSPEC.
        env["COMSPEC"] = os.environ.get("COMSPEC", env["SystemRoot"] + r"\System32\cmd.exe")
    started = time.monotonic()
    out_path = Path(cwd) / f".out-{time.monotonic_ns()}.txt"
    job = None
    try:
        with out_path.open("wb") as out:
            try:
                if os.name == "nt":
                    job = _Job(memory_mb)
                    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                            creationflags=0x4 | 0x08000000)  # CREATE_SUSPENDED | CREATE_NO_WINDOW
                    job.adopt(proc)
                else:
                    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, preexec_fn=_limits)
            except (FileNotFoundError, PermissionError, OSError) as exc:
                return {"exit_code": None, "tool_error": f"{type(exc).__name__}: {exc}", "timed_out": False,
                        "elapsed_s": round(time.monotonic() - started, 3), "output": "", "output_truncated": False}
            try:
                proc.wait(timeout=timeout_s)
                timed_out = False
            except subprocess.TimeoutExpired:
                if job:
                    job.terminate()
                else:
                    os.killpg(proc.pid, 9)
                proc.wait()
                timed_out = True
            if job:
                job.terminate()  # leftovers of a finished tool must not outlive the step
        raw = out_path.read_bytes()
    finally:
        if job:
            job.close()
        for _ in range(20):  # a terminated child may hold the output file for a moment
            try:
                out_path.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.05)
    return {"exit_code": proc.returncode, "timed_out": timed_out, "elapsed_s": round(time.monotonic() - started, 3),
            "output": raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"), "output_truncated": len(raw) > MAX_OUTPUT_BYTES}


def versions():
    out = {}
    for name, args in (("iverilog", ["-V"]), ("vvp", ["-V"]), ("verilator", ["--version"])):
        with tempfile.TemporaryDirectory(prefix="ver-") as d:
            r = execute([str(tool(name)), *args], d, 20)
        out[name] = (r.get("output") or r.get("tool_error") or "").strip().splitlines()[:1]
    return out


def workdir(sources):
    """Fresh directory holding copies of the given sources at their hdl/... relative paths."""
    d = Path(tempfile.mkdtemp(prefix="sim-"))
    for rel in sources:
        dst = d / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
    return d
