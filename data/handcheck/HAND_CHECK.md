# 手工核对样本（合成数据，13 行）

`handcheck.csv` 是手写的小样本，用来证明程序统计数字正确。下面的期望值是逐行手算的，不是程序输出；`tests/test_chip_analysis.py::test_hand_check_sample` 会把程序结果与这些手算值逐项比较。必测项目只有 VREF 和 IDDQ（见本目录的 `items.json`）。

## 逐行说明（行号 = 文件物理行号，表头为第 1 行）

| 行 | 芯片 | 项目 | 轮次 | 值 | 状态 | 说明 |
|---:|---|---|---:|---|---|---|
| 2 | D001 | VREF | 0 | 1.2000 V | PASS | |
| 3 | D001 | IDDQ | 0 | 2.100 mA | PASS | |
| 4 | D002 | VREF | 0 | 1185.0 mV = 1.185 V | FAIL | 单位 mV，换算后低于下限 1.19 |
| 5 | D002 | IDDQ | 0 | 3.000 mA | PASS | |
| 6 | D002 | VREF | 1 | 1195.0 mV = 1.195 V | PASS | 重测通过 |
| 7 | D003 | VREF | 0 | 1.2050 V | PASS | |
| 8 | D003 | IDDQ | 0 | 5.400 mA | FAIL | |
| 9 | D003 | IDDQ | 1 | 5.200 mA | FAIL | 重测仍失败 |
| 10 | D003 | IDDQ | 1 | 5.200 mA | FAIL | 与第 9 行完全相同，去重 |
| 11 | D004 | VREF | 0 | 1.1950 V | PASS | |
| 12 | D004 | IDDQ | 0 | 空 | FAIL | 缺失值 |
| 13 | D005 | VREF | 0 | 1.2040 V | PASS | |
| 14 | D005 | IDDQ | 0 | 空 | SKIP | 必测项目被跳过 |

## 手算结果

1. 输入 13 行，第 10 行是重复行，去重后 12 行。
2. 测试记录通过率：PASS 行是第 2、3、5、6、7、11、13 行，共 7 行；FAIL 行是第 4、8、9、12 行，共 4 行；SKIP 1 行不进分母。7 / 11 = 0.636363…，保留四位小数为 **0.6364**。
3. 最终结果（每个芯片项目取最大轮次）：
   - D001：VREF PASS，IDDQ PASS → **PASS**
   - D002：VREF 取轮次 1 为 PASS，IDDQ PASS → **PASS**（首测时 VREF FAIL）
   - D003：IDDQ 取轮次 1 为 FAIL → **FAIL**
   - D004：IDDQ FAIL（缺失值，测试机记为 FAIL）→ **FAIL**
   - D005：IDDQ SKIP → **INCOMPLETE**
4. 芯片 5 颗：PASS 2，FAIL 2，INCOMPLETE 1。
   - 良率(全部) = 2 / 5 = **0.4**
   - 良率(仅完整) = 2 / (2 + 2) = **0.5**
   - 首测良率(全部)：只有 D001 首测全部通过，1 / 5 = **0.2**
5. 失败最多的项目：IDDQ 的最终 FAIL 芯片为 D003、D004，共 **2** 颗，FAIL 行（含重测）为第 8、9、12 行，共 **3** 行；VREF 的最终 FAIL 芯片为 **0** 颗，FAIL 行为第 4 行，共 **1** 行。
6. 质量检查应报出：第 10 行 duplicate_row（重复自第 9 行）；第 12 行 missing_value；第 4、6 行 unit_converted（mV→V）。没有 status_inconsistent，因为每行记录状态都与上下限判定一致。
