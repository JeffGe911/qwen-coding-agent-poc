"""Recompute key metrics in SQLite and compare with the Python results (independent second path)."""
import sqlite3

SQL_RECORD_RATE = """
SELECT run_id, lot_id,
       SUM(status = 'PASS') AS pass_rows,
       SUM(status = 'FAIL') AS fail_rows,
       ROUND(1.0 * SUM(status = 'PASS') / NULLIF(SUM(status IN ('PASS', 'FAIL')), 0), 4) AS record_pass_rate
FROM m GROUP BY run_id, lot_id ORDER BY run_id, lot_id
"""
SQL_FINAL_FAILS = """
WITH top AS (
  SELECT run_id, chip_key, test_item, MAX(retest) AS r FROM m GROUP BY run_id, chip_key, test_item
), chosen AS (
  SELECT m.run_id, m.chip_key, m.test_item, COUNT(*) AS n, MAX(m.conflict) AS conflict, MAX(m.status) AS status
  FROM m JOIN top ON m.run_id = top.run_id AND m.chip_key = top.chip_key AND m.test_item = top.test_item AND m.retest = top.r
  GROUP BY m.run_id, m.chip_key, m.test_item
)
SELECT test_item, SUM(n = 1 AND conflict = 0 AND status = 'FAIL') AS final_fail_chips
FROM chosen GROUP BY test_item ORDER BY final_fail_chips DESC, test_item
"""


def cross_check(clean, record_rows, top_rows):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE m (run_id TEXT, lot_id TEXT, chip_key TEXT, test_item TEXT, retest INTEGER, status TEXT, conflict INTEGER)")
    db.executemany("INSERT INTO m VALUES (?,?,?,?,?,?,?)", [(r["run_id"], r["lot_id"], r["chip_key"], r["test_item"], r["retest"] or 0, r["status"],
                                                             int("conflicting_measurement" in r["flags"])) for r in clean])
    sql_rates = [dict(zip(("run_id", "lot_id", "pass_rows", "fail_rows", "record_pass_rate"), row)) for row in db.execute(SQL_RECORD_RATE)]
    sql_fails = dict(db.execute(SQL_FINAL_FAILS).fetchall())
    py_rates = [{k: r[k] for k in ("run_id", "lot_id", "pass_rows", "fail_rows", "record_pass_rate")} for r in record_rows]
    py_fails = {r["test_item"]: r["final_fail_chips"] for r in top_rows}
    return {"record_pass_rate_match": sql_rates == py_rates, "final_fail_chips_match": all(sql_fails.get(k) == v for k, v in py_fails.items()),
            "sql": {"record_pass_rate": SQL_RECORD_RATE.strip(), "final_fails": SQL_FINAL_FAILS.strip()},
            "sql_record_pass_rate": sql_rates, "sql_final_fail_chips": sql_fails}
