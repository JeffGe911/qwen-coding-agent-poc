def summarize_results(results):
    summary = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        status = result.get("status")
        if status == "passed":
            summary["passed"] += 1
        elif status == "failed":
            summary["failed"] += 1
        elif status == "skipped":
            summary["skipped"] += 1
        else:
            raise ValueError(f"Unknown status: {status}")
    total_executed = summary["passed"] + summary["failed"]
    summary["pass_rate"] = round(summary["passed"] / total_executed, 4) if total_executed else 0.0
    return summary
