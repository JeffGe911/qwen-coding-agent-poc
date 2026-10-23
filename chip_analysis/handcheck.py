"""Compare program output on data/handcheck/handcheck.csv with values computed by hand (HAND_CHECK.md)."""
from collections import Counter
from pathlib import Path

from . import metrics as M
from .loader import load_dir, load_items
from .quality import check

EXPECTED = {
    "rows_input": 13, "rows_after_dedup": 12,
    "record_pass_rate": 0.6364,
    "chips": 5, "chips_pass": 2, "chips_fail": 2, "chips_incomplete": 1,
    "yield_all": 0.4, "yield_complete_only": 0.5, "first_pass_yield_all": 0.2,
    "IDDQ_final_fail_chips": 2, "IDDQ_fail_rows": 3, "VREF_final_fail_chips": 0, "VREF_fail_rows": 1,
    "duplicate_row_lines": [10], "missing_value_lines": [12], "unit_converted_lines": [4, 6], "status_inconsistent_lines": [],
}


def run(directory):
    directory = Path(directory)
    spec = load_items(directory / "items.json")
    records, reports = load_dir(directory, spec)
    clean, issues, profile = check(records, reports, spec)
    finals = M.results(clean)
    final_chips, first_chips = M.chip_outcomes(clean, spec), M.chip_outcomes(clean, spec, "first")
    y = M.yield_table(final_chips, first_chips, ("run_id",))[0]
    rate = M.record_pass_rate(clean, ("run_id",))[0]
    items = {r["test_item"]: r for r in M.top_items(M.item_failures(clean, finals), 10)}
    outcomes = Counter(c["outcome"] for c in final_chips)
    lines = lambda rule: sorted(i["source_line"] for i in issues if i["rule"] == rule)
    actual = {
        "rows_input": profile["input_rows"], "rows_after_dedup": profile["rows_after_dedup"],
        "record_pass_rate": rate["record_pass_rate"],
        "chips": y["chips"], "chips_pass": outcomes["PASS"], "chips_fail": outcomes["FAIL"], "chips_incomplete": outcomes["INCOMPLETE"],
        "yield_all": y["yield_all"], "yield_complete_only": y["yield_complete_only"], "first_pass_yield_all": y["first_pass_yield_all"],
        "IDDQ_final_fail_chips": items["IDDQ"]["final_fail_chips"], "IDDQ_fail_rows": items["IDDQ"]["fail_rows_incl_retests"],
        "VREF_final_fail_chips": items["VREF"]["final_fail_chips"], "VREF_fail_rows": items["VREF"]["fail_rows_incl_retests"],
        "duplicate_row_lines": lines("duplicate_row"), "missing_value_lines": lines("missing_value"),
        "unit_converted_lines": lines("unit_converted"), "status_inconsistent_lines": lines("status_inconsistent"),
    }
    return {k: {"expected": EXPECTED[k], "actual": actual[k]} for k in EXPECTED}
