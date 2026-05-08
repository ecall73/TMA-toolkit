---
name: xsai-tma-tooling
description: Guide for using tools/TMA-toolkit to apply XSPerfAccumulate instrumentation from YAML presets and generate report/plot artifacts from simulation logs.
---

# XSAI TMA Tooling

当任务是“基于 YAML 自动插桩 + 从仿真日志自动分析/作图”时，使用本技能。

## 前置要求

- 使用 UV 管理环境与执行命令（无需 sudo）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project tools/TMA-toolkit
```

- 优先使用 Make 入口，保证参数和目录行为一致：

```bash
make -C tools/TMA-toolkit help
```

## 适用范围

- `tools/TMA-toolkit/`
- `tools/TMA-toolkit/presets/`
- `tools/TMA-toolkit/reports/`
- `tools/TMA-toolkit/examples/`

## Demo-first 工作流

在接触真实大日志前，先用仓库内示例验证工具链、口径和输出形态：

```bash
uv run --project tools/TMA-toolkit tma-toolkit report \
  --preset cute/default \
  --log tools/TMA-toolkit/examples/emu-error.default.log \
  --out-prefix tools/TMA-toolkit/examples/tma-cute
```

核对点：

- `examples/tma-cute_values.csv`
- `examples/tma-cute_consistency.json`
- `examples/tma-cute_report.rpt`

再切换到真实日志执行分析：

```bash
uv run --project tools/TMA-toolkit tma-toolkit report --preset <module>/<preset> --log <emu-log>
```

## 标准流程

1. 选择 preset（例如 `cute/default`）
2. 执行 `apply`（建议先 `--dry-run`）
3. 运行仿真（沿用 `make run-emu ...`）
4. 执行 `report` 生成 `CSV/PNG/MD/JSON/RPT`

推荐 Make 命令：

```bash
make -C tools/TMA-toolkit apply-dry PRESET=<module>/<preset>
make -C tools/TMA-toolkit apply PRESET=<module>/<preset>
make -C tools/TMA-toolkit report PRESET=<module>/<preset> LOG=<log-path>
make -C tools/TMA-toolkit report-strict PRESET=<module>/<preset> LOG=<log-path>
```

等价底层命令（需要时）：

```bash
uv run --project tools/TMA-toolkit tma-toolkit apply --preset <module>/<preset> --dry-run
uv run --project tools/TMA-toolkit tma-toolkit apply --preset <module>/<preset>
uv run --project tools/TMA-toolkit tma-toolkit report --preset <module>/<preset> --log <emu-log>
```

常用扩展目标：

```bash
make -C tools/TMA-toolkit report-prefix PRESET=<module>/<preset> LOG=<log> OUT_PREFIX=log/tma-out
make -C tools/TMA-toolkit report-no-backup PRESET=<module>/<preset> LOG=<log>
make -C tools/TMA-toolkit show-vars PRESET=<module>/<preset> LOG=<log>
make -C tools/TMA-toolkit demo
```

退出语义约束：

- `report` / `report-prefix` / `report-no-backup` 是容错模式（始终返回 0）。
- `report-strict` / `report-prefix-strict` / `report-no-backup-strict` 是门禁模式（一致性失败返回非 0）。

## RPT-first 分析方法

Agent 分析时默认顺序：

1. 先读 `report.rpt`
2. 再读 `values.csv`
3. 最后看 `combined.png`

RPT 重点字段：

- `META`：spec/log/run_id
- `CONSISTENCY`：先看 FAIL 项
- `TOP_CONTRIBUTORS`：快速定位大头
- `TREE_VIEW` / `CHART_GROUP_VIEW`：还原分层关系

禁止仅依赖图片/OCR下结论。图像用于确认，不是唯一信息源。

## PR/评审结论输出约束

- 有 `examples/tma-cute_report.rpt` 时，优先引用 RPT/CSV 的数值证据。
- 明确区分“结果现象”和“一致性检查状态”。
- `report-strict`（或底层 `report --strict`）非零返回时，不等于工具故障；先核对 `consistency.json` 与 RPT。

## 关键约束

- 插桩通过 TMA-toolkit 落地，不手工维护插桩块。
- `accumulate_only` 口径下，插入块仅包含 `XSPerfAccumulate(...)`。
- preset 插桩格式为 `instrumentation.sites + instrumentation.points`。
- 口径变更优先改 preset YAML，而不是改 Python 工具逻辑。
