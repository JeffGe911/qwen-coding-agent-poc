# 合成芯片测试数据：字段说明

**这是合成数据。** 由 `python -m chip_analysis synth --out data/synthetic` 以固定种子 20261023 生成，重复执行得到逐字节相同的文件。字段结构只是示例，不代表任何公司的真实数据结构。接入真实数据时，应先按实际字段改写 `items.json`，并扩充 `chip_analysis/loader.py` 中的列名映射，再重新确认指标口径。

## 文件

| 文件 | 内容 | 刻意注入的问题 |
|---|---|---|
| `raw/R1_LOT-A01.csv` | 运行 R1（2026-10-21，测试程序 TP-1.4），批次 LOT-A01 | 3 个缺失值（值为空、状态 FAIL）；6 行完全重复 |
| `raw/R1_LOT-A02.csv` | 运行 R1，批次 LOT-A02；晶圆 W02 的 IDDQ 整体偏高 2.4 mA | VREF 全部以 mV 记录，值和上下限一起换了单位 |
| `raw/R2_LOT-A02_rescreen.csv` | 运行 R2（2026-10-22，TP-1.5）对 LOT-A02 复测；TP-1.5 的 IDDQ 读数低 0.3 mA | 列名不同（Lot、Die、TestName、Result、Pass/Fail 等），状态写作 P/F/S，日期用斜杠 |
| `raw/R2_LOT-B01.csv` | 运行 R2，新批次 LOT-B01 | IDDQ 上限 5.5（其他文件为 5.0）；8 颗芯片的 FMAX 为 SKIP；1 个 9999 异常值；2 行状态与上下限矛盾；1 行缺状态；1 对同轮次冲突测量 |
| `raw/R2_empty.csv` | 0 字节 | 空文件 |
| `logs/tester_R2_2026-10-22.log` | R2 的自由文本测试机日志 | 1 行被截断的 FAIL 记录 |
| `items.json` | 测试项目、规范单位、上下限、必测项目、单位换算系数 | — |
| `INJECTED_ISSUES.json` | 所有注入问题的位置，用作质量检查的“标准答案” | — |

## 规范字段（每行 = 一次测量）

| 字段 | 含义 | 示例 |
|---|---|---|
| lot_id | 批次 | LOT-A01 |
| wafer_id | 晶圆 | W01、W02 |
| die_id | 晶圆上的芯片编号；芯片唯一键为 lot/wafer/die | D017 |
| test_item | 测试项目 | VREF、IDDQ、LEAK、FMAX、TEMP_OFFSET |
| value | 测量值；SKIP 时为空 | 2.413 |
| unit | 单位 | V、mV、mA、uA、MHz、degC |
| lower / upper | 下限 / 上限（与 value 同单位） | 0 / 5 |
| status | 测试机判定 | PASS、FAIL、SKIP（复测文件写作 P/F/S） |
| test_time | 测试时间 | 2026-10-21 08:00:42 |
| retest | 同一运行内的重测轮次，0 为首测 | 0、1 |
| run_id | 测试运行 | R1、R2 |
| test_program | 测试程序版本 | TP-1.4、TP-1.5 |

| 项目 | 规范单位 | 下限 | 上限 |
|---|---|---:|---:|
| VREF | V | 1.19 | 1.21 |
| IDDQ | mA | 0 | 5.0 |
| LEAK | uA | 0 | 1.0 |
| FMAX | MHz | 980 | 1300 |
| TEMP_OFFSET | degC | -2 | 2 |

5 个项目都是必测项目。每个运行内，首测失败的芯片项目会重测一次（retest = 1）。

## 已知的生成规律（只有合成数据才“知道答案”）

生成器在 LOT-A02 晶圆 W02 上注入了 IDDQ 偏移，并让 TP-1.5 的 IDDQ 读数系统性偏低 0.3 mA。分析程序的输入里不包含这些信息，分析结果只能显示“相关”和“差异”。真实数据中，这类差异的原因需要工艺和测试工程师确认。
