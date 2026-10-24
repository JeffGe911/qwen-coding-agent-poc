"""Score triage results against hand-labelled gold answers (gold is never shown to a model).

Per sample and in aggregate:
- category / result / side accuracy over gold tests (a gold test the engine did not report counts as wrong);
- precision / recall of flagged tests (result fail or not_run);
- citations: valid = file is the log, line exists, quote is a substring of that physical line (>= 6 chars);
  relevant = valid and the line is one of the gold evidence lines of that test;
- unknown rate, tests reported that are not in the log ("unmatched"), log_status accuracy, expected-flag recall.
"""
import re

FLAGGED = ("fail", "not_run")


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def citation_ok(c, log):
    line = log.line(c.get("line")) if isinstance(c.get("line"), int) else None
    quote = norm(c.get("quote"))
    return bool(c.get("file") == log.name and line is not None and len(quote) >= 6 and quote in norm(line))


def score_sample(pred, gold, log):
    gtests, ptests = gold["tests"], {t["test_id"]: t for t in pred.get("tests", [])}
    rows = []
    for tid, g in gtests.items():
        p = ptests.get(tid)
        cites = (p or {}).get("evidence", [])
        valid = [c for c in cites if citation_ok(c, log)]
        relevant = [c for c in valid if c["line"] in g["evidence_lines"]]
        rows.append({"test_id": tid, "gold": {k: g[k] for k in ("result", "category", "side")}, "pred": {k: (p or {}).get(k) for k in ("result", "category", "side")},
                     "category_ok": bool(p and p["category"] == g["category"]), "result_ok": bool(p and p["result"] == g["result"]),
                     "side_ok": bool(p and p["side"] == g["side"]), "citations": len(cites), "citations_valid": len(valid), "citations_relevant": len(relevant),
                     "has_relevant_citation": bool(relevant) if g["evidence_lines"] else None})
    flagged_gold = {t for t, g in gtests.items() if g["result"] in FLAGGED}
    flagged_pred = {t for t, p in ptests.items() if p.get("result") in FLAGGED}
    unmatched = sorted(set(ptests) - set(gtests))
    return {"sample_id": gold["sample_id"], "log_status_ok": pred.get("log_status") == gold["log_status"],
            "log_status": {"gold": gold["log_status"], "pred": pred.get("log_status")}, "tests": rows,
            "flagged": {"tp": sorted(flagged_gold & flagged_pred), "fp": sorted(flagged_pred - flagged_gold), "fn": sorted(flagged_gold - flagged_pred)},
            "unmatched_tests": unmatched, "flags_expected": gold.get("flags", []),
            "flags_found": sorted(set(gold.get("flags", [])) & set(pred.get("flags", []))), "unknown_tests": sum(1 for p in ptests.values() if p.get("category") == "unknown"),
            "extra_citations_on_unmatched": sum(len(ptests[t].get("evidence", [])) for t in unmatched)}


def aggregate(samples):
    tests = [t for s in samples for t in s["tests"]]
    tp = sum(len(s["flagged"]["tp"]) for s in samples)
    fp = sum(len(s["flagged"]["fp"]) for s in samples)
    fn = sum(len(s["flagged"]["fn"]) for s in samples)
    cites = sum(t["citations"] for t in tests)
    need = [t for t in tests if t["has_relevant_citation"] is not None]
    ratio = lambda a, b: round(a / b, 4) if b else None
    return {"samples": len(samples), "gold_tests": len(tests),
            "category_accuracy": ratio(sum(t["category_ok"] for t in tests), len(tests)),
            "result_accuracy": ratio(sum(t["result_ok"] for t in tests), len(tests)),
            "side_accuracy": ratio(sum(t["side_ok"] for t in tests), len(tests)),
            "flagged_precision": ratio(tp, tp + fp), "flagged_recall": ratio(tp, tp + fn), "flagged_counts": {"tp": tp, "fp": fp, "fn": fn},
            "citations": cites, "citation_valid_rate": ratio(sum(t["citations_valid"] for t in tests), cites),
            "citation_relevant_rate": ratio(sum(t["citations_relevant"] for t in tests), cites),
            "tests_with_relevant_citation": ratio(sum(bool(t["has_relevant_citation"]) for t in need), len(need)),
            "unknown_rate": ratio(sum(s["unknown_tests"] for s in samples), len(tests)),
            "unmatched_tests": sum(len(s["unmatched_tests"]) for s in samples),
            "log_status_accuracy": ratio(sum(s["log_status_ok"] for s in samples), len(samples)),
            "flag_recall": ratio(sum(len(s["flags_found"]) for s in samples), sum(len(s["flags_expected"]) for s in samples))}
