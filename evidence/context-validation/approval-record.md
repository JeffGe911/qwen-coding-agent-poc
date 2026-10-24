# 审批记录：report_pass_rate（r1 与 r2 各一个新运行）

审批在对话中进行。展示给 Jeff 的内容是下面的完整差异、两个运行的路径与审批摘要，以及审阅意见：skipped 不计入分母、四位小数、没有执行用例时为 0.0、缺失/大小写不符/未知状态抛出 ValueError、不修改输入。chip_final_yield 本轮没有提案进入审批。

提问（原文）：

- 是否批准 r1（4096×2）上的 report_pass_rate 新运行执行 pytest？摘要 e844f457…aaf3c2，差异见上方。（选项：批准 / 拒绝 / 暂不决定）
- 是否批准 r2（8192×1）上的 report_pass_rate 新运行执行 pytest？摘要 8bb2baba…c194a，代码与 r1 那份相同。（选项：批准 / 拒绝 / 暂不决定）

Jeff 的回答：两项都选“批准”。随后按批准代为执行 decide 命令（控制台输出见 approval-console.txt），审计事件里的 reviewer 记为 `Jeff (approved in chat)`。

## r1-7b-ctx4096

- 运行：`evidence/context-validation/r1-7b-ctx4096/runs/20261023T213152Z-report_pass_rate-ef9dab37`
- 审批摘要：`e844f45762c2aa52a129c41361ed145144a7055c2de44ea3090ff30d55aaf3c2`
- 提案代码 SHA-256：`4833cb6613943ef495d224c2d016c6aa347265f566613a7f65eae7f7f960e10d`
- 批准时间：2026-10-24T04:16:37.576135+00:00；结果：succeeded，pytest 21/21

```diff
--- before/solution.py
+++ after/solution.py
@@ -1,6 +1,15 @@
 def summarize_results(results):
     summary = {"passed": 0, "failed": 0, "skipped": 0}
     for result in results:
-        summary[result["status"]] += 1
-    summary["pass_rate"] = summary["passed"] / len(results) if results else 0.0
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
+    summary["pass_rate"] = round(summary["passed"] / total_executed, 4) if total_executed else 0.0
     return summary
```

## r2-7b-ctx8192-np1

- 运行：`evidence/context-validation/r2-7b-ctx8192-np1/runs/20261023T213441Z-report_pass_rate-d6d474cf`
- 审批摘要：`8bb2babaa5df77ddad3386505fc00b5af6c50bb3240c5a1d1f23f992a13c194a`
- 提案代码 SHA-256：`4833cb6613943ef495d224c2d016c6aa347265f566613a7f65eae7f7f960e10d`
- 批准时间：2026-10-24T04:16:36.723758+00:00；结果：succeeded，pytest 21/21

```diff
--- before/solution.py
+++ after/solution.py
@@ -1,6 +1,15 @@
 def summarize_results(results):
     summary = {"passed": 0, "failed": 0, "skipped": 0}
     for result in results:
-        summary[result["status"]] += 1
-    summary["pass_rate"] = summary["passed"] / len(results) if results else 0.0
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
+    summary["pass_rate"] = round(summary["passed"] / total_executed, 4) if total_executed else 0.0
     return summary
```

