# TMA-toolkit（Top-down Micro-architecture Analysis）

English version: [README.md](README.md)

`tools/TMA-toolkit` 是一套 YAML 驱动的性能分析工具：

- `apply`：按 preset 自动插入/刷新 `XSPerfAccumulate(...)`
- `report`：解析仿真日志并生成 **HTML + RPT + consistency JSON**

## 输出契约

报告产物统一为：

- `report.html`（主可视化报告，多选项卡）
- `report.rpt`（面向 AI/Agent 的结构化伪图形文本）
- `consistency.json`（一致性检查调试文件）

旧的 `CSV/PNG/MD` 报告产物已不再生成。

## 快速开始

### 1）环境准备

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project tools/TMA-toolkit
```

### 2）查看 preset

```bash
make -C tools/TMA-toolkit list-presets
```

### 3）插桩

```bash
make -C tools/TMA-toolkit apply-dry PRESET=cute/default
make -C tools/TMA-toolkit apply PRESET=cute/default
```

### 4）生成报告

归档模式：

```bash
make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log
```

前缀模式：

```bash
make -C tools/TMA-toolkit report-prefix PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
make -C tools/TMA-toolkit report-prefix-strict PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
```

## 输出路径与命名

### 归档模式

```text
tools/TMA-toolkit/reports/<module>/<preset>/<run-id>/
  report.html
  report.rpt
  consistency.json
```

### 前缀模式

```text
<OUT_PREFIX>_report.html
<OUT_PREFIX>_report.rpt
<OUT_PREFIX>_consistency.json
```

## HTML 报告结构

HTML 报告采用与 RedLeaves 同类的多选项卡交互，固定 4 个页签：

1. `Overview`：元信息、关键指标、direct/derived 指标
2. `Breakdown`：层级树、分组视图、比率行
3. `Charts`：Plotly 交互图（group 分解图 + top contributors）
4. `Consistency`：一致性检查与诊断信息

Plotly 通过 CDN 引入（`include_plotlyjs='cdn'`）。

## 内置 preset

- `cute/default`
- `cute/legacy_v1`
- `cute/matrix_hpm_sim_report`（report-only，消费 `MAT_SIM_*`）

## 样例流程

### A）default 教学样例（`examples/`）

```bash
make -C tools/TMA-toolkit demo
```

产物：

- `tools/TMA-toolkit/examples/tma-cute_report.html`
- `tools/TMA-toolkit/examples/tma-cute_report.rpt`
- `tools/TMA-toolkit/examples/tma-cute_consistency.json`

### B）HPM sim 样例（直接使用仓库日志）

```bash
make -C tools/TMA-toolkit report-prefix-strict \
  PRESET=cute/matrix_hpm_sim_report \
  LOG=log/emu-error.log \
  OUT_PREFIX=tools/TMA-toolkit/reports/cute/matrix_hpm_sim_report/latest
```

产物：

- `.../latest_report.html`
- `.../latest_report.rpt`
- `.../latest_consistency.json`

## Make Targets

完整说明见：

```bash
make -C tools/TMA-toolkit help
```

核心 target：

- `sync`
- `list-presets`
- `show-vars`
- `apply` / `apply-dry`
- `report` / `report-strict`
- `report-prefix` / `report-prefix-strict`
- `report-no-backup` / `report-no-backup-strict`（兼容 target）
- `demo` / `demo-strict`

## strict 语义

- `report*` 容错版本始终返回 0（Makefile 中 `|| true`）。
- `*-strict` 在 `error` 级检查失败时返回非 0。

## 常见问题

### 缺少 `plotly`

```bash
uv sync --project tools/TMA-toolkit
```

### `apply` 锚点未命中

- 调整 preset 的 `anchor_regex`。
- 不要手工维护自动生成的插桩块。

### strict 报告失败

- 先看 `consistency.json` 与 `report.rpt`。
- 这通常是口径问题，不一定是工具崩溃。

## 设计原则

- 模块语义沉淀在 preset YAML。
- 工具层保持通用与可复用。
- 优先改 preset，不要在 Python 中硬编码模块特例。
- 插桩以 `apply` 自动化为主，避免长期手工维护插桩。
