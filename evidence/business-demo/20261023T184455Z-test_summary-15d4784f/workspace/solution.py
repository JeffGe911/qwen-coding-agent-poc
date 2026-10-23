def summarize_results(results):
    summary = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        summary[result["status"]] += 1
    summary["pass_rate"] = summary["passed"] / len(results) if results else 0.0
    return summary
