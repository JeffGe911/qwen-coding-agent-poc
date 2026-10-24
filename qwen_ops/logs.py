"""JSON-lines logger with size-based rotation. Never logs prompts, completions or tokens."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .health import now


def json_logger(path, name, max_bytes=1_000_000, backups=5):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"qwen_ops.{name}.{path}")
    if not logger.handlers:
        handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    def log(event, **data):
        record = {"at_utc": now(), "event": event, **data}
        logger.info(json.dumps(record, ensure_ascii=False, default=str))
        return record
    return log


def compact(health):
    """Small, prompt-free summary of a health result for logs."""
    c = health["checks"]
    out = {"status": health["status"]}
    for key in ("process", "port", "api", "model", "residency", "disk"):
        if key in c:
            out[key] = c[key].get("ok")
    if "api" in c:
        out["api_seconds"] = c["api"].get("seconds")
        if c["api"].get("error"):
            out["api_error"] = c["api"]["error"][:160]
    if "model" in c:
        out["golden"] = {g["id"]: [g["ok"], g.get("seconds")] for g in c["model"]["golden"]}
    if "residency" in c and c["residency"].get("gpu_fraction") is not None:
        out["gpu_fraction"] = c["residency"]["gpu_fraction"]
        out["context_length"] = c["residency"].get("context_length")
    return out
