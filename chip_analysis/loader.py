"""Read test-result CSV files into canonical records that keep a pointer to the original line.

Column names, status labels and units are normalized through an explicit items spec
(JSON). The bundled spec describes the SYNTHETIC dataset only; real data needs its own.
"""
import csv
from datetime import datetime
import json
from pathlib import Path

CANONICAL = ["lot_id", "wafer_id", "die_id", "test_item", "value", "unit", "lower", "upper",
             "status", "test_time", "retest", "run_id", "test_program"]
REQUIRED_COLUMNS = {"lot_id", "wafer_id", "die_id", "test_item", "value", "unit", "status"}
ALIASES = {
    "lot": "lot_id", "lot_id": "lot_id", "lotid": "lot_id",
    "wafer": "wafer_id", "wafer_id": "wafer_id",
    "die": "die_id", "die_id": "die_id", "chip": "die_id", "chip_id": "die_id",
    "test_item": "test_item", "testname": "test_item", "test_name": "test_item", "item": "test_item",
    "value": "value", "result": "value", "meas": "value", "measurement": "value",
    "unit": "unit", "units": "unit",
    "lower": "lower", "lolim": "lower", "lo_limit": "lower", "low_limit": "lower",
    "upper": "upper", "hilim": "upper", "hi_limit": "upper", "high_limit": "upper",
    "status": "status", "pass/fail": "status", "result_flag": "status",
    "test_time": "test_time", "timestamp": "test_time", "time": "test_time",
    "retest": "retest", "retest_round": "retest",
    "run_id": "run_id", "run": "run_id",
    "test_program": "test_program", "program": "test_program",
}
STATUS_MAP = {"PASS": "PASS", "P": "PASS", "FAIL": "FAIL", "F": "FAIL", "SKIP": "SKIP", "S": "SKIP"}
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def load_items(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    return spec


def to_float(text):
    text = (text or "").strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_time(text):
    text = (text or "").strip()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            pass
    return None


def convert(value, unit, target, factors):
    """Return value in target unit, or raise KeyError when no factor is defined."""
    if value is None or unit == target:
        return value
    # Round away binary noise (e.g. 1.005 V * 1000 -> 1004.9999999999999 mV) so limits compare exactly.
    return round(value * factors[f"{unit}->{target}"], 9)


def load_file(path, spec, root):
    """Return (records, file_report). Never raises on bad rows; problems are recorded."""
    path = Path(path)
    name = path.relative_to(root).as_posix() if root else path.name
    report = {"file": name, "bytes": path.stat().st_size, "rows": 0, "status": "ok", "column_map": {}, "unmapped_columns": []}
    if report["bytes"] == 0:
        report["status"] = "empty_file"
        return [], report
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        report["status"] = "empty_file"
        return [], report
    mapping = {}
    for index, column in enumerate(header):
        key = ALIASES.get(column.strip().lower())
        if key:
            mapping[index] = key
            report["column_map"][column] = key
        else:
            report["unmapped_columns"].append(column)
    missing = REQUIRED_COLUMNS - set(mapping.values())
    if missing:
        report["status"] = "missing_columns:" + ",".join(sorted(missing))
        return [], report
    records = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        raw = {mapping[i]: cells[i] if i < len(cells) else "" for i in mapping}
        records.append(normalize(raw, spec, name, line_no, lines[line_no - 1]))
    report["rows"] = len(records)
    return records, report


def normalize(raw, spec, source_file, source_line, raw_line):
    item = raw.get("test_item", "").strip()
    unit = raw.get("unit", "").strip()
    status_text = raw.get("status", "").strip().upper()
    record = {
        "source_file": source_file, "source_line": source_line, "raw_line": raw_line,
        "lot_id": raw.get("lot_id", "").strip(), "wafer_id": raw.get("wafer_id", "").strip(),
        "die_id": raw.get("die_id", "").strip(), "test_item": item,
        "raw_value": raw.get("value", ""), "raw_unit": unit,
        "raw_lower": raw.get("lower", ""), "raw_upper": raw.get("upper", ""),
        "status": STATUS_MAP.get(status_text), "raw_status": raw.get("status", ""),
        "test_time": parse_time(raw.get("test_time")), "run_id": raw.get("run_id", "").strip(),
        "test_program": raw.get("test_program", "").strip(),
        "retest": int(raw["retest"]) if raw.get("retest", "").strip().isdigit() else None,
        "flags": [],
    }
    value, lower, upper = to_float(raw.get("value")), to_float(raw.get("lower")), to_float(raw.get("upper"))
    item_spec = spec["items"].get(item)
    target = item_spec["unit"] if item_spec else unit
    record["unit"] = target
    try:
        record["value"] = convert(value, unit, target, spec["unit_factors"])
        record["lower"] = convert(lower, unit, target, spec["unit_factors"])
        record["upper"] = convert(upper, unit, target, spec["unit_factors"])
        if unit != target:
            record["flags"].append(f"unit_converted:{unit}->{target}")
    except KeyError:
        record.update(value=None, lower=None, upper=None, unit=unit)
        record["flags"].append(f"unit_unknown:{unit}")
    if item_spec is None:
        record["flags"].append("unknown_test_item")
    if raw.get("value", "").strip() and value is None:
        record["flags"].append("value_not_numeric")
    record["chip_key"] = f"{record['lot_id']}/{record['wafer_id']}/{record['die_id']}"
    return record


def load_dir(directory, spec):
    directory = Path(directory)
    records, reports = [], []
    for path in sorted(directory.rglob("*.csv")):
        rows, report = load_file(path, spec, directory)
        records.extend(rows)
        reports.append(report)
    return records, reports
