def summarize_chip_yield(rows, required_items):
    chips = {}
    for row in rows:
        value = float(row["value"])
        passed = float(row["lower"]) <= value <= float(row["upper"])
        chips.setdefault(row["chip_id"], []).append(passed)
    passed_chips = [chip for chip, results in chips.items() if any(results)]
    return {
        "chips": len(chips),
        "passed_chips": len(passed_chips),
        "yield": len(passed_chips) / len(chips),
        "failed_chip_ids": [chip for chip in chips if chip not in passed_chips],
    }
