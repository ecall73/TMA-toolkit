---
name: xsai-tma-tooling
description: Guide for using tools/TMA-toolkit to apply XSPerfAccumulate instrumentation from YAML presets and generate HTML/RPT/JSON analysis artifacts from simulation logs.
---

# XSAI TMA Tooling

当任务是“基于 YAML 自动插桩 + 从仿真日志自动分析并输出 HTML/RPT”时，使用本技能。

## 前置要求

- 使用 UV 管理环境与执行命令：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project tools/TMA-toolkit
```

- 优先使用 Make 入口：

```bash
make -C tools/TMA-toolkit help
```

## 适用范围

- `tools/TMA-toolkit/`
- `tools/TMA-toolkit/presets/`
- `tools/TMA-toolkit/reports/`
- `tools/TMA-toolkit/examples/`

## 标准流程

1. 选 preset（例如 `cute/default`）
2. `apply-dry` 预览 + anchor 检查
3. `apply` 写入插桩
4. 跑仿真
5. `report` 生成 HTML/RPT/JSON

推荐命令：

```bash
make -C tools/TMA-toolkit apply-dry PRESET=<module>/<preset>
make -C tools/TMA-toolkit apply PRESET=<module>/<preset>
make -C tools/TMA-toolkit report PRESET=<module>/<preset> LOG=<log-path>
make -C tools/TMA-toolkit report-strict PRESET=<module>/<preset> LOG=<log-path>
```

前缀输出模式：

```bash
make -C tools/TMA-toolkit report-prefix PRESET=<module>/<preset> LOG=<log> OUT_PREFIX=log/tma-out
make -C tools/TMA-toolkit report-prefix-strict PRESET=<module>/<preset> LOG=<log> OUT_PREFIX=log/tma-out
```

## 输出产物（新契约）

- `report.html`：主可视化报告（多选项卡）
- `report.rpt`：结构化伪图形文本，适合 AI/Agent 阅读
- `consistency.json`：一致性检查结果

不再生成 `CSV/PNG/MD`。

## RPT-first 分析方式

默认分析顺序：

1. 先看 `report.rpt`
2. 再看 `report.html` 的图与表
3. 最后核对 `consistency.json`

重点区块：

- `[CONSISTENCY]`
- `[TREE_VIEW]`
- `[CHART_GROUP_VIEW]`
- `[TOP_CONTRIBUTORS]`
- `[DIAGNOSTIC_NOTES]`

## 示例

### default 教学样例

```bash
make -C tools/TMA-toolkit demo
```

### HPM sim 样例（仓库现有日志）

```bash
make -C tools/TMA-toolkit report-prefix-strict \
  PRESET=cute/matrix_hpm_sim_report \
  LOG=log/emu-error.log \
  OUT_PREFIX=tools/TMA-toolkit/reports/cute/matrix_hpm_sim_report/latest
```

## 关键约束

- 插桩通过 toolkit 落地，不手工长期维护插桩块。
- 口径变更优先修改 preset YAML。
- `report-strict` 失败先看语义一致性，不要直接判断为工具故障。
