"""Framework tests for chip_analysis (SYNTHETIC data). These test the program, not the model."""
import csv
import json
from pathlib import Path

import pytest

from chip_analysis import assist, handcheck, metrics as M, synth
from chip_analysis.engineering import compare_runs, extract_log_failures, review_list
from chip_analysis.loader import load_dir, load_items
from chip_analysis.pipeline import analyze
from chip_analysis.quality import check
from chip_analysis.sqlcheck import cross_check

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = synth.generate(tmp_path_factory.mktemp("synthetic"))
    spec = load_items(out / "items.json")
    records, reports = load_dir(out / "raw", spec)
    clean, issues, profile = check(records, reports, spec)
    return out, spec, records, reports, clean, issues, profile


def test_hand_check_sample_matches_manual_arithmetic():
    result = handcheck.run(ROOT / "data" / "handcheck")
    mismatches = {k: v for k, v in result.items() if v["expected"] != v["actual"]}
    assert not mismatches


def test_generator_is_deterministic(tmp_path):
    a, b = synth.generate(tmp_path / "a"), synth.generate(tmp_path / "b")
    for path in sorted((a / "raw").glob("*.csv")) + [a / "logs" / "tester_R2_2026-10-22.log"]:
        assert path.read_bytes() == (b / path.relative_to(a)).read_bytes()


def test_every_injected_issue_with_a_line_is_detected(dataset):
    out, spec, records, reports, clean, issues, profile = dataset
    injected = json.loads((out / "INJECTED_ISSUES.json").read_text(encoding="utf-8"))["issues"]
    found = {(i["rule"], "raw/" + i["source_file"], i["source_line"]) for i in issues if "source_line" in i}
    lined = [x for x in injected if "line" in x and x["file"].startswith("raw/")]
    assert lined and all((x["rule"], x["file"], x["line"]) in found for x in lined)
    conflict = next(x for x in injected if x["rule"] == "conflicting_measurement")
    assert all(("conflicting_measurement", conflict["file"], line) in found for line in conflict["lines"])
    assert any(i["rule"] == "empty_file" and i["file"] == "R2_empty.csv" for i in issues)


def test_column_aliases_and_units_are_normalized(dataset):
    out, spec, records, reports, clean, issues, profile = dataset
    rescreen = next(f for f in reports if f["file"] == "R2_LOT-A02_rescreen.csv")
    assert rescreen["status"] == "ok" and rescreen["column_map"]["Pass/Fail"] == "status" and not rescreen["unmapped_columns"]
    vref_mv = [r for r in clean if r["source_file"] == "R1_LOT-A02.csv" and r["test_item"] == "VREF"]
    assert vref_mv and all(r["unit"] == "V" and r["lower"] == 1.19 and r["upper"] == 1.21 for r in vref_mv)
    assert not any(i["rule"] == "status_inconsistent" and i["source_file"] == "R1_LOT-A02.csv" for i in issues)


def test_review_rows_trace_back_to_the_original_line(dataset):
    out, spec, records, reports, clean, issues, profile = dataset
    rows = review_list(issues)
    assert rows
    for item in rows:
        lines = (out / "raw" / item["source_file"]).read_text(encoding="utf-8").splitlines()
        assert lines[item["source_line"] - 1] == item["raw_line"]


def test_sql_and_python_agree(dataset):
    out, spec, records, reports, clean, issues, profile = dataset
    items = M.item_failures(clean, M.results(clean))
    result = cross_check(clean, M.record_pass_rate(clean, ("run_id", "lot_id")), M.top_items(items, 99))
    assert result["record_pass_rate_match"] and result["final_fail_chips_match"]


def test_record_rate_and_chip_yield_are_different_metrics(dataset):
    out, spec, records, reports, clean, issues, profile = dataset
    rates = {(r["run_id"], r["lot_id"]): r["record_pass_rate"] for r in M.record_pass_rate(clean, ("run_id", "lot_id"))}
    yields = {(r["run_id"], r["lot_id"]): r for r in M.yield_table(M.chip_outcomes(clean, spec), M.chip_outcomes(clean, spec, "first"), ("run_id", "lot_id"))}
    b01 = yields[("R2", "LOT-B01")]
    assert b01["incomplete"] == 10 and b01["yield_all"] < b01["yield_complete_only"]
    assert rates[("R2", "LOT-B01")] != b01["yield_all"]


def test_concentration_flags_the_shifted_wafer_only(dataset):
    out, spec, records, reports, clean, issues, profile = dataset
    flagged = M.concentration(M.results(clean), clean, ("lot_id", "wafer_id"))
    assert [(f["run_id"], f["lot_id"], f["wafer_id"], f["test_item"]) for f in flagged] == [("R1", "LOT-A02", "W02", "IDDQ")]


def test_log_extraction_and_malformed_line(dataset):
    out = dataset[0]
    res = extract_log_failures(out / "logs" / "tester_R2_2026-10-22.log")
    assert res["failures"] and all(f["raw_line"].endswith(f"limit=[{f['lower']},{f['upper']}]") for f in res["failures"])
    assert len(res["unparsed"]) == 1 and "truncated" in res["unparsed"][0]["raw_line"]


def test_run_comparison_on_shared_lot(dataset):
    clean = dataset[4]
    diff = compare_runs(clean, "R1", "R2", ["LOT-A02"])
    assert diff["overlap_chip_items"] == 400
    assert set(diff["counts"]) <= {"new_failure", "fixed", "other_change"}
    for row in diff["rows"]:
        assert row["R1_source"].startswith("R1_LOT-A02.csv:") and row["R2_source"].startswith("R2_LOT-A02_rescreen.csv:")


def test_directory_with_only_an_empty_file(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "empty.csv").write_bytes(b"")
    result = analyze(tmp_path / "raw", ROOT / "data" / "handcheck" / "items.json", tmp_path / "out")
    assert result["profile"]["input_rows"] == 0 and result["quality_counts"] == {"empty_file": 1}
    from chip_analysis.report import render
    assert render(result, tmp_path / "out").exists()


FACTS = {"yield_by_lot": [{"run_id": "R1", "lot_id": "LOT-A", "yield_all": 0.9, "incomplete": 0},
                          {"run_id": "R2", "lot_id": "LOT-B", "yield_all": 0.8375, "incomplete": 10}],
         "quality_counts": {"duplicate_row": 6}}


def test_explanation_checks_catch_misattribution_missing_keys_and_no_numbers():
    parsed = {"summary": "s", "uncertainties": [], "next_checks": [], "findings": [
        {"claim": "R1 的 LOT-A 良率为 0.8375", "evidence": ["yield_by_lot[0].yield_all"]},
        {"claim": "R2 的 LOT-B 良率为 0.8375，重复行 6 条", "evidence": ["yield_by_lot[1].yield_all", "quality_counts.duplicate_row"]},
        {"claim": "良率较低", "evidence": ["yield_by_lot[0].nonexistent"]},
        {"claim": "良率为 0.123", "evidence": ["yield_by_lot"]}]}
    checks, _ = assist.check_explanation(parsed, FACTS)
    assert checks[0]["numbers_misattributed"] == ["0.8375"]
    assert checks[1]["numbers_misattributed"] == [] and checks[1]["evidence_keys_found"]
    assert not checks[2]["claim_has_number"] and checks[2]["missing_evidence_keys"] == ["yield_by_lot[0].nonexistent"]
    assert checks[3]["numbers_not_in_facts"] == ["0.123"]


def test_route_rejects_commands_outside_the_allowlist(monkeypatch):
    def fake(self, path, body=None):
        return {"choices": [{"message": {"content": json.dumps({"command": "shell", "top_n": 5, "date": "", "base_run": "", "new_run": "", "reason": "x"})}}]}
    monkeypatch.setattr(assist.Client, "request", fake)
    with pytest.raises(ValueError, match="allowlist"):
        assist.route("rm -rf", "http://127.0.0.1:1/v1", "fixture")


def test_assist_refuses_non_loopback_endpoints():
    with pytest.raises(ValueError, match="loopback"):
        assist.explain({}, "https://api.example.com/v1", "fixture")
