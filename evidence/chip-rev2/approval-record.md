# 审批记录（2026-10-24）

审批在对话中进行。展示给 Jeff 的是下面每份提案的完整差异、运行路径与审批摘要，以及审阅意见。
A、B 两份的意见是都有明显错误：mV 行把上下限也除以 1000；空值、冲突行、最大重测轮次处理不对；A 按测量而不是按芯片计数；B 第一次取值会触发 TypeError。预计通过数很低，但执行它们才能得到业务层结果。

提问与回答（原文）：

- 是否批准 A 组提案 1（摘要 4b7fbdf7…）执行 pytest（公开测试 + holdout）？ → 批准
- 是否批准 B 组提案 3（摘要 4cc17f80…）执行 pytest？这是 B 组最后一次提案。 → 批准
- r2 激活后 validate 产生了一个 report_pass_rate 运行（摘要 d7a674f3…，提示词 1844 + 输出 366，stop）。要执行它吗？ → 批准执行

之后按批准代为执行 decide；reviewer 记为 `Jeff (approved in chat)`。

## A 组提案 1

- 运行：`evidence/chip-rev2/A/runs/20261024T055010Z-chip_final_yield-bad4d535`
- 审批摘要：`4b7fbdf71ce192ac5e16db8e783243b3f6059dc0cf78b92bda127cc586d79a8c`
- 提案代码 SHA-256：`af6c90a330f402d5ce2a358d91b2a3efecedb0c1f82ed39b2b7cdb7a0abda4e3`

```diff
--- before/solution.py
+++ after/solution.py
@@ -1,13 +1,54 @@
 def summarize_chip_yield(rows, required_items):
     chips = {}
+    duplicates_ignored = 0
+    missing_values = 0
+
     for row in rows:
-        value = float(row["value"])
-        passed = float(row["lower"]) <= value <= float(row["upper"])
-        chips.setdefault(row["chip_id"], []).append(passed)
-    passed_chips = [chip for chip, results in chips.items() if any(results)]
+        chip_id = row["chip_id"]
+        test_item = row["test_item"]
+        value = row["value"]
+        unit = row["unit"]
+        lower = row["lower"]
+        upper = row["upper"]
+        retest = row["retest"]
+
+        if unit not in ["V", "mV"]:
+            raise ValueError(f"Invalid unit: {unit}")
+
+        if unit == "mV":
+            value = float(value) / 1000
+            lower = float(lower) / 1000
+            upper = float(upper) / 1000
+
+        if value == "":
+            missing_values += 1
+            continue
+
+        value = float(value)
+        lower = float(lower)
+        upper = float(upper)
+        retest = int(retest)
+
+        if (chip_id, test_item, retest) in chips:
+            duplicates_ignored += 1
+            continue
+
+        passed = lower <= value <= upper
+        chips[(chip_id, test_item, retest)] = passed
+
+    passed_chips = [chip_id for chip_id, test_item, retest in chips if chips[(chip_id, test_item, retest)]]
+    failed_chip_ids = [chip_id for chip_id, test_item, retest in chips if not chips[(chip_id, test_item, retest)]]
+
+    if not chips:
+        yield_value = 0.0
+    else:
+        yield_value = len(passed_chips) / len(chips)
+
     return {
         "chips": len(chips),
         "passed_chips": len(passed_chips),
-        "yield": len(passed_chips) / len(chips),
-        "failed_chip_ids": [chip for chip in chips if chip not in passed_chips],
+        "yield": yield_value,
+        "failed_chip_ids": sorted(failed_chip_ids),
+        "duplicates_ignored": duplicates_ignored,
+        "missing_values": missing_values,
     }
```

## B 组提案 3

- 运行：`evidence/chip-rev2/B/runs/20261024T055029Z-chip_final_yield-8acefa5a`
- 审批摘要：`4cc17f80ce5ebb2de3b4803eaefc0cfd97726e86f535aedb7a4d31070bd4a66a`
- 提案代码 SHA-256：`82847bd494d4b7d7a953b64b92b610c6d6a9b4191c5c5b8a09cedf4ce4c99b4f`

```diff
--- before/solution.py
+++ after/solution.py
@@ -1,13 +1,74 @@
 def summarize_chip_yield(rows, required_items):
     chips = {}
+    duplicates_ignored = 0
+    missing_values = 0
+
     for row in rows:
-        value = float(row["value"])
-        passed = float(row["lower"]) <= value <= float(row["upper"])
-        chips.setdefault(row["chip_id"], []).append(passed)
-    passed_chips = [chip for chip, results in chips.items() if any(results)]
+        chip_id = row["chip_id"]
+        test_item = row["test_item"]
+        value = row["value"]
+        unit = row["unit"]
+        lower = row["lower"]
+        upper = row["upper"]
+        retest = int(row["retest"])
+
+        if chip_id not in chips:
+            chips[chip_id] = {}
+
+        if test_item not in chips[chip_id]:
+            chips[chip_id][test_item] = []
+
+        existing_rows = chips[chip_id][test_item]
+        for existing_row in existing_rows:
+            if all(existing_row[k] == row[k] for k in row):
+                duplicates_ignored += 1
+                break
+        else:
+            existing_rows.append(row)
+
+    passed_chips = 0
+    failed_chip_ids = set()
+
+    for chip_id, test_items in chips.items():
+        if all(item in test_items for item in required_items):
+            results = [row for test_item, rows in test_items.items() for row in rows]
+            final_results = {}
+
+            for row in results:
+                value = float(row["value"])
+                unit = row["unit"]
+                lower = float(row["lower"])
+                upper = float(row["upper"])
+                retest = int(row["retest"])
+
+                if unit == "mV":
+                    value /= 1000
+                    lower /= 1000
+                    upper /= 1000
+
+                if retest > final_results.get((chip_id, test_item), -1)[2]:
+                    final_results[(chip_id, test_item)] = (value, unit, retest)
+
+            passed = True
+            for chip_id, test_item in required_items:
+                if (chip_id, test_item) not in final_results or not lower <= final_results[(chip_id, test_item)][0] <= upper:
+                    passed = False
+                    break
+
+            if passed:
+                passed_chips += 1
+            else:
+                failed_chip_ids.add(chip_id)
+        else:
+            failed_chip_ids.add(chip_id)
+
+    yield_value = passed_chips / len(chips) if chips else 0.0
+
     return {
         "chips": len(chips),
-        "passed_chips": len(passed_chips),
-        "yield": len(passed_chips) / len(chips),
-        "failed_chip_ids": [chip for chip in chips if chip not in passed_chips],
+        "passed_chips": passed_chips,
+        "yield": round(yield_value, 4),
+        "failed_chip_ids": sorted(failed_chip_ids),
+        "duplicates_ignored": duplicates_ignored,
+        "missing_values": missing_values,
     }
```

## r2 激活后 validate 的 report_pass_rate

- 运行：`evidence/release-r2-activation/r2-active/runs/20261024T054525Z-report_pass_rate-c4e3c588`
- 审批摘要：`d7a674f3c54247e837db733b1c458bf8e634faa1be57afa041e11a2df572ba99`
- 提案代码 SHA-256：`9143089da5285bfd5fc3d56a850520ef081f61ca587958a3a0828372d67e0b2f`

```diff
--- before/solution.py
+++ after/solution.py
@@ -1,6 +1,15 @@
 def summarize_results(results):
     summary = {"passed": 0, "failed": 0, "skipped": 0}
     for result in results:
-        summary[result["status"]] += 1
-    summary["pass_rate"] = summary["passed"] / len(results) if results else 0.0
-    return summary
+        status = result.get("status")
+        if status == "passed":
+            summary["passed"] += 1
+        elif status == "failed":
+            summary["failed"] += 1
+        elif status == "skipped":
+            summary["skipped"] += 1
+        else:
+            raise ValueError(f"Unknown status: {status}")
+    total_executed = summary["passed"] + summary["failed"]
+    pass_rate = summary["passed"] / total_executed if total_executed else 0.0
+    return {"passed": summary["passed"], "failed": summary["failed"], "skipped": summary["skipped"], "pass_rate": round(pass_rate, 4)}
```


## C 组提案 1（qwen2.5-coder:14b）

审阅意见：整行元组和按芯片的数据混放在同一个字典里，汇总时对 `True` 做 `in` 会抛出 TypeError；`len(chips) - 1` 计数错误；空值会先做 float('')；超限值被记为缺失；汇总用的是最后一行的 lower/upper；空输入返回 chips = -1。做对的部分：只换算 value 的 mV、保留最大重测轮次、同轮次值不同时报冲突。

- 是否批准 C 组（14b）提案 1（摘要 5c2dc57b…）执行 pytest？失败会按规则用 14b 自动重新提案（最多再 2 次，每次都会再请你审批）。 → 批准

- 运行：`evidence/chip-rev2/C/runs/20261024T064229Z-chip_final_yield-f35c49b9`
- 审批摘要：`5c2dc57b3dfd6823db8f53a93acaa2b7a942f9440360e65eef260bc72c6219b4`
- 提案代码 SHA-256：`b33b12a12d0289f2acc477ebede5e405d4811b24befff8a887e7f0cffc462bef`

```diff
--- before/solution.py
+++ after/solution.py
@@ -1,13 +1,56 @@
 def summarize_chip_yield(rows, required_items):
     chips = {}
+    duplicates_ignored = 0
+    missing_values = 0
     for row in rows:
-        value = float(row["value"])
-        passed = float(row["lower"]) <= value <= float(row["upper"])
-        chips.setdefault(row["chip_id"], []).append(passed)
-    passed_chips = [chip for chip, results in chips.items() if any(results)]
+        key = tuple(row.values())
+        if key in chips:
+            duplicates_ignored += 1
+            continue
+        chips[key] = True
+        chip_id = row['chip_id']
+        test_item = row['test_item']
+        value = row['value']
+        unit = row['unit']
+        lower = float(row['lower'])
+        upper = float(row['upper'])
+        retest = int(row['retest'])
+        if unit not in ('V', 'mV'):
+            raise ValueError(f'Unknown unit: {unit}')
+        if unit == 'mV':
+            value = float(value) / 1000
+        else:
+            value = float(value)
+        if value == '' or value < lower or value > upper:
+            missing_values += 1
+            continue
+        if chip_id not in chips:
+            chips[chip_id] = {}
+        if test_item not in chips[chip_id]:
+            chips[chip_id][test_item] = (retest, value)
+        else:
+            if chips[chip_id][test_item][0] == retest:
+                if chips[chip_id][test_item][1] != value:
+                    raise ValueError(f'Conflicting values for chip {chip_id}, test {test_item}, retest {retest}')
+            elif chips[chip_id][test_item][0] < retest:
+                chips[chip_id][test_item] = (retest, value)
+    passed_chips = 0
+    failed_chip_ids = []
+    for chip_id, tests in chips.items():
+        if chip_id == 'chip_id':
+            continue
+        if all(test in tests and lower <= tests[test][1] <= upper for test in required_items):
+            passed_chips += 1
+        else:
+            failed_chip_ids.append(chip_id)
+    failed_chip_ids.sort()
+    total_chips = len(chips) - 1  # Subtract 1 to exclude the 'chip_id' key
+    yield_value = passed_chips / total_chips if total_chips > 0 else 0.0
     return {
-        "chips": len(chips),
-        "passed_chips": len(passed_chips),
-        "yield": len(passed_chips) / len(chips),
-        "failed_chip_ids": [chip for chip in chips if chip not in passed_chips],
-    }
+        'chips': total_chips,
+        'passed_chips': passed_chips,
+        'yield': round(yield_value, 4),
+        'failed_chip_ids': failed_chip_ids,
+        'duplicates_ignored': duplicates_ignored,
+        'missing_values': missing_values
+    }
```

