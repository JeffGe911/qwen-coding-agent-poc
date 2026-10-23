def summarize_results(results):
    summary = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        if "status" not in result:
            raise ValueError("Missing status")
        if result["status"] not in summary:
            raise ValueError(f"Unknown status: {result["status"]}")
        summary[result["status"]] += 1
    executed = summary["passed"] + summary["failed"]
    pass_rate = round(summary["passed"] / executed, 4) if executed else 0.0
    return {"passed": summary["passed"], "failed": summary["failed"], "skipped": summary["skipped"], "pass_rate": pass_rate}
