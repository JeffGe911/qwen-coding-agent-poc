"""Bounded, scoped log reading. Every later citation refers to the physical 1-based line numbers kept here."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

MAX_LOG_BYTES = 5_000_000


@dataclass
class Log:
    name: str          # how reports and citations refer to the file (path relative to the root it was read from)
    lines: list        # physical lines without line terminators; lines[0] is line 1
    size: int
    sha256: str
    empty: bool

    def line(self, n):
        return self.lines[n - 1] if 1 <= n <= len(self.lines) else None


def read_log(path, root):
    """Read one log that must be a regular file under root, at most MAX_LOG_BYTES."""
    root = Path(root).resolve()
    path = Path(path)
    full = (path if path.is_absolute() else root / path).resolve()
    if root != full and root not in full.parents:
        raise ValueError(f"{path} is outside the allowed folder {root}")
    if full.is_symlink() or not full.is_file():
        raise ValueError(f"{path} is not a regular file")
    size = full.stat().st_size
    if size > MAX_LOG_BYTES:
        raise ValueError(f"{path} is {size} bytes; the limit is {MAX_LOG_BYTES}")
    raw = full.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # a final newline does not start another line
    lines = [line[:-1] if line.endswith("\r") else line for line in lines]
    return Log(name=full.relative_to(root).as_posix(), lines=lines, size=size, sha256=hashlib.sha256(raw).hexdigest(), empty=not text.strip())
