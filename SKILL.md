---
name: xsai-tma-tooling
description: Guide for using tools/TMA-toolkit to apply XSPerfAccumulate instrumentation from YAML presets and generate report/plot artifacts from simulation logs.
---

# XSAI TMA Tooling

当任务是“基于 YAML 自动插桩 + 从仿真日志自动分析/作图”时，使用本技能。

适用范围：
- `tools/TMA-toolkit/`
- `tools/TMA-toolkit/presets/`
- `tools/TMA-toolkit/reports/`

## 目标

- 通过 `preset` 驱动，不手改 Scala 插桩逻辑
- 使用同一份 YAML 同时定义：
  - 插桩规则（`instrumentation`）
  - 分析与出图规则（`analysis`）

## 标准流程

1. 选择 preset（例如 `cute/default` 或 `cute/legacy_27ac003_4cdc89a`）。
2. 执行 `apply`（可先 `--dry-run`）。
3. 运行既有仿真流程（`make run-emu ...`）。
4. 执行 `report` 生成 CSV/PNG/MD/JSON。

推荐命令：

```bash
python3 tools/TMA-toolkit/tma.py apply --preset <module>/<preset> --dry-run
python3 tools/TMA-toolkit/tma.py apply --preset <module>/<preset>
python3 tools/TMA-toolkit/tma.py report --preset <module>/<preset> --log <emu-log>
```

Makefile 等价命令：

```bash
make -C tools/TMA-toolkit apply PRESET=<module>/<preset>
make -C tools/TMA-toolkit report PRESET=<module>/<preset> LOG=<log-path>
```

## 关键约束

- 插桩应通过 TMA-toolkit 工具落地，不建议手工改 `XSPerfAccumulate`。
- `accumulate_only` 策略下，插入块应仅包含 `XSPerfAccumulate(...)` 行。
- 更改计数器口径时，优先修改 preset YAML，而不是改 Python 逻辑。
- 做历史口径复现时，确保 `direct_counters / derived_counters / hierarchy / chart_groups_abs / display_aliases` 同步更新。

## 常见任务模板

### A. 新增一个计数器口径（同模块）

1. 在对应 preset 的 `instrumentation.points` 增加 `name/expr/site`。
2. 在 `analysis.direct_counters` 注册该计数器。
3. 必要时更新 `derived_counters`、`hierarchy`、`chart_groups_abs`、`display_aliases`。
4. 用固定日志回放并验证结果稳定。

### B. 复刻历史版本口径

1. 从目标提交提取 `XSPerfAccumulate` 名称与表达式。
2. 新建独立 legacy preset（不要覆盖 default）。
3. 通过 `report --out-prefix` 与历史 CSV/PNG 对比集合与数值。

### C. 只做分析不改代码

直接执行 `report`，不执行 `apply`。

## 验证建议

- 插桩验证：
  - `apply --dry-run` 检查 `missing_anchors`。
  - 重复执行 `apply`，第二次应无新增叠加。
- 分析验证：
  - 对比历史基线 CSV 的计数项集合和数值。
  - 检查 `consistency.json` 与报告中的一致性检查项。

## 易错点

- 误用 `--out-prefix` 导致输出在 `log/`，而非 `tools/TMA-toolkit/reports/`。
- 只改 `instrumentation` 不改 `analysis`，导致图表缺项或口径不闭合。
- 改了 `preset` 却仍在用旧 `run-id` 对比，误判结果。

