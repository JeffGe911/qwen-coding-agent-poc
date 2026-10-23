"""Guards the frozen chip_final_yield acceptance tests. Framework test, not a model result."""
import hashlib
import json
import shutil

import pytest

from qwen_agent.policy import validate
from qwen_agent.runner import execute
from qwen_agent.workflow import FILES, TASKS

TASK = TASKS / "chip_final_yield"

# Proves the frozen tests are satisfiable within the code policy. Never sent to the model.
REFERENCE = '''def summarize_chip_yield(rows, required_items):
    seen = set()
    unique = []
    duplicates = 0
    for row in rows:
        key = tuple(sorted(row.items()))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(row)
    rounds = {}
    for row in unique:
        if row["unit"] not in ("V", "mV"):
            raise ValueError("unknown unit: " + row["unit"])
        key = (row["chip_id"], row["test_item"], int(row["retest"]))
        if key in rounds:
            raise ValueError("conflicting rows for the same retest round")
        rounds[key] = row
    final = {}
    for (chip, item, number), row in rounds.items():
        if (chip, item) not in final or number > final[(chip, item)][0]:
            final[(chip, item)] = (number, row)
    missing = 0
    ok = {}
    for key, (number, row) in final.items():
        if row["value"] == "":
            missing += 1
            ok[key] = False
            continue
        value = float(row["value"])
        if row["unit"] == "mV":
            value = value / 1000
        ok[key] = float(row["lower"]) <= value <= float(row["upper"])
    chips = sorted(set(row["chip_id"] for row in unique))
    passed = [c for c in chips if all(ok.get((c, item), False) for item in required_items)]
    return {
        "chips": len(chips),
        "passed_chips": len(passed),
        "yield": round(len(passed) / len(chips), 4) if chips else 0.0,
        "failed_chip_ids": [c for c in chips if c not in passed],
        "duplicates_ignored": duplicates,
        "missing_values": missing,
    }
'''


def run_with(tmp_path, code=None):
    for name in FILES:
        shutil.copy(TASK / name, tmp_path / name)
    if code is not None:
        (tmp_path / "solution.py").write_text(code, encoding="utf-8")
    return execute(tmp_path, "restricted")


def test_task_files_match_frozen_digests():
    frozen = json.loads((TASK / "frozen.json").read_text(encoding="utf-8"))
    for name, expected in frozen["sha256"].items():
        assert hashlib.sha256((TASK / name).read_bytes()).hexdigest() == expected, f"{name} changed after freezing"


def test_buggy_original_is_policy_valid_and_fails_baseline(tmp_path):
    validate((TASK / "solution.py").read_text(encoding="utf-8"))
    result = run_with(tmp_path)
    frozen = json.loads((TASK / "frozen.json").read_text(encoding="utf-8"))
    assert result["exit_code"] == 1 and result["errors"] == 0
    assert (result["tests"], result["passed"]) == tuple(frozen["baseline_original"])


def test_reference_solution_passes_everything(tmp_path):
    validate(REFERENCE)
    result = run_with(tmp_path, REFERENCE)
    assert result["exit_code"] == 0 and result["passed"] == result["tests"] == 22
