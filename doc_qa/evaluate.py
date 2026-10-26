"""Score doc-QA answers against question files written with gold facts and gold source lines.

Answerable questions: correct = an answer was shown and it contains every gold fact (literal tokens such as an option
name, compared case-insensitively with backticks ignored); supported = at least one shown citation overlaps a gold
source line range; retrieval_hit = a retrieved passage overlaps it (diagnostic: retrieval miss vs generation miss).
Unanswerable questions: abstained = "not found" was shown; any shown answer is a hallucination.
"""
from .answer import norm


def overlaps(file, lines, gold):
    return any(file == g["file"] and lines[0] <= g["lines"][1] and lines[1] >= g["lines"][0] for g in gold)


def score(rec, q):
    shown = rec["shown"]
    given = len(shown.get("citations", [])) + len(shown.get("rejected_citations", []))
    row = {"id": q["id"], "language": q.get("language"), "answerable": q["answerable"], "status": rec["status"], "found": shown["found"],
           "citations_given": given, "citations_valid": len(shown.get("citations", [])), "seconds": rec.get("seconds")}
    if q["answerable"]:
        facts = [f for f in q["gold_facts"] if norm(f) in norm(shown["answer"])] if shown["found"] else []
        row.update(facts_found=len(facts), facts_total=len(q["gold_facts"]), correct=shown["found"] and len(facts) == len(q["gold_facts"]),
                   supported=shown["found"] and any(overlaps(c["file"], c["lines"], q["gold_sources"]) for c in shown["citations"]),
                   retrieval_hit=any(overlaps(r["file"], r["lines"], q["gold_sources"]) for r in rec["retrieved"]))
    else:
        row.update(abstained=not shown["found"], hallucinated=shown["found"])
    return row


def aggregate(rows):
    a = [r for r in rows if r["answerable"]]
    u = [r for r in rows if not r["answerable"]]
    frac = lambda k, rs: f"{sum(bool(r[k]) for r in rs)}/{len(rs)}" if rs else "-"
    secs = sorted(r["seconds"] for r in rows if r.get("seconds") is not None)
    return {"questions": len(rows), "answerable": len(a), "unanswerable": len(u),
            "correct": frac("correct", a), "found_on_answerable": frac("found", a), "supported": frac("supported", a),
            "retrieval_hit": frac("retrieval_hit", a), "wrongly_not_found": f"{sum(not r['found'] for r in a)}/{len(a)}",
            "abstained_on_unanswerable": frac("abstained", u), "hallucinated": frac("hallucinated", u),
            "citations_valid": f"{sum(r['citations_valid'] for r in rows)}/{sum(r['citations_given'] for r in rows)}",
            "request_failed": sum(r["status"] == "request_failed" for r in rows), "invalid_output": sum(r["status"] == "invalid_output" for r in rows),
            "seconds_median": secs[len(secs) // 2] if secs else None, "seconds_max": secs[-1] if secs else None}
