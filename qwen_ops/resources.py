"""Host resource checks shared by everything that loads a model on the laptop.

Before a model is loaded: available RAM, commit headroom (current commit limit minus committed bytes; page-file growth
is not counted, because relying on it pages the operator's other programs out), free VRAM and AC power must all pass.
`require()` raises instead of printing, so a caller cannot carry on by accident (doc-QA's first index build did: its
ad-hoc check printed the problem and the next command ran anyway).
"""
import ctypes
import subprocess

THRESHOLDS = {"min_available_mb": 4096, "min_commit_headroom_mb": 4096, "min_free_vram_mb": 6500, "abort_available_mb": 2048, "abort_commit_headroom_mb": 2048}


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    """Available RAM and commit headroom in MiB (Windows)."""
    s = MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(s)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
        raise OSError("GlobalMemoryStatusEx failed")
    mb = 2**20
    return {"total_mb": s.ullTotalPhys // mb, "available_mb": s.ullAvailPhys // mb, "commit_limit_mb": s.ullTotalPageFile // mb,
            "commit_headroom_mb": s.ullAvailPageFile // mb}


def gpu():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0]
    used, total, util, temp = (int(float(x)) for x in out.split(","))
    return {"vram_used_mb": used, "vram_total_mb": total, "vram_free_mb": total - used, "gpu_util_pct": util, "gpu_temp_c": temp}


def ac_power():
    """True / False on a laptop, None when the machine reports no battery."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty PowerOnline)"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return {"True": True, "False": False}.get(out)


def problems(mem, g, ac=None, t=THRESHOLDS, vram_needed_mb=None):
    """Reasons not to load a model now (empty list = go)."""
    out = []
    if mem["available_mb"] < t["min_available_mb"]:
        out.append(f"available RAM {mem['available_mb']} MiB < {t['min_available_mb']}")
    if mem["commit_headroom_mb"] < t["min_commit_headroom_mb"]:
        out.append(f"commit headroom {mem['commit_headroom_mb']} MiB < {t['min_commit_headroom_mb']} (page-file growth not counted)")
    need = t["min_free_vram_mb"] if vram_needed_mb is None else vram_needed_mb
    if g["vram_free_mb"] < need:
        out.append(f"free VRAM {g['vram_free_mb']} MiB < {need}")
    if ac is False:
        out.append("not on AC power (the GPU is power-capped on battery)")
    return out


def must_abort(mem, t=THRESHOLDS):
    return mem["available_mb"] < t["abort_available_mb"] or mem["commit_headroom_mb"] < t["abort_commit_headroom_mb"]


class ResourceError(RuntimeError):
    pass


def require(vram_needed_mb=None):
    """The current readings, or ResourceError listing why a model must not be loaded now."""
    mem, g, ac = memory(), gpu(), ac_power()
    found = problems(mem, g, ac, vram_needed_mb=vram_needed_mb)
    if found:
        raise ResourceError("not loading a model: " + "; ".join(found))
    return {"memory": mem, "gpu": g, "ac_power": ac}
