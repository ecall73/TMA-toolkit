# TMA-toolkit（Top-down Micro-architecture Analysis）

English version: [README.md](README.md)

`tools/TMA-toolkit` 是一套“YAML 驱动”的性能分析基础设施：

- `apply`：按 preset 自动插入/刷新 `XSPerfAccumulate(...)`
- `report`：按同一份 preset 解析日志并生成 `CSV/PNG/MD/JSON/RPT`

## 基础设施价值

没有基础设施时，常见做法是手工（或临时脚本）往 RTL 里加 `XSPerfAccumulate(...)`。这种方式短期快，但长期问题明显：

- 计数器代码容易长期留在分支或主线，事件越堆越多。
- 不同人按不同理解插桩，口径不一致，结果难复现。
- 临时插桩容易漏删、误删或改坏条件。
- 评审混入大量观测改动，干扰真实功能改动。

`TMA-toolkit` 把“观测口径”抽离到 YAML：

- 单一真源：计数器、层级、派生、检查、作图都在 preset。
- 按需插桩：需要分析时 apply，不需要时不长期保留。
- 自动化与幂等：统一插入/替换逻辑，减少人工错误。
- 报告标准化：同一 preset + 同一 log 得到可复现结果。

结论：新增分析需求优先“改或新增 preset”，而不是手工堆 `XSPerfAccumulate`。

## 背景与目标

Top-down 的核心是把总 stall 逐层归因：

1. 先看 L1 大类：`Memory / Compute / Dependency`
2. 再看 L2 子项：具体阻塞类型
3. 最后看 L3 来源：来自 AML/BML/CML/Compute 哪一侧

目标是用可复现的数据链路快速回答瓶颈问题。

## 工具全景（职责边界）

- `tma.py`：统一 CLI 入口
- `tma_apply.py`：插桩引擎
- `tma_report.py`：日志解析、派生计算、一致性检查、制图、`.rpt`
- `presets/<module>/<preset>.yaml`：模块口径（插桩+分析）
- `reports/`：归档报告
- `examples/`：单教学示例

默认 preset：

- `cute/default`：L1 互斥 `Memory/Compute/Dependency`

## Preset 格式

TMA-toolkit 的插桩描述格式定义如下：

- `instrumentation.sites`：定义插桩位点（文件、锚点、缩进、import、block id）
- `instrumentation.points`：定义计数项（`name`、`site`、`expr`）

`instrumentation` 使用 `sites + points` 组织；模块差异统一在该结构中表达。

## Make Targets（推荐入口）

日常使用优先通过 `make -C tools/TMA-toolkit <target>`：

| Target | 作用 | 关键输入 | 退出语义 | 输出位置 |
| --- | --- | --- | --- | --- |
| `sync` | 按 `uv.lock` 安装/同步依赖 | 无 | 失败返回非 0 | 本地 `.venv` |
| `list-presets` | 列出可用 preset | 无 | 恒为 0 | 标准输出 |
| `show-vars` | 打印解析后的变量与路径 | 可选变量 | 恒为 0 | 标准输出 |
| `apply-dry` | 预览插桩变更并检查锚点 | `PRESET`、`BASELINE_REF`、`REPO_ROOT` | 失败返回非 0 | 标准输出 |
| `apply` | 将插桩写入 RTL 文件 | `PRESET`、`BASELINE_REF`、`REPO_ROOT` | 失败返回非 0 | RTL 文件 |
| `report` | 归档模式生成报告（容错） | `PRESET`、`LOG`、`OUT_ROOT`、`RUN_ID`、`BACKUP_LOG` | 恒为 0（`|| true`） | `reports/<module>/<preset>/<run-id>/` |
| `report-strict` | 归档模式生成报告（门禁） | 同 `report` | 严格检查失败返回非 0 | 同 `report` |
| `report-prefix` | 前缀模式生成报告（容错） | `PRESET`、`LOG`、`OUT_PREFIX` | 恒为 0（`|| true`） | `<OUT_PREFIX>_*` |
| `report-prefix-strict` | 前缀模式生成报告（门禁） | `PRESET`、`LOG`、`OUT_PREFIX` | 严格检查失败返回非 0 | `<OUT_PREFIX>_*` |
| `report-no-backup` | 归档模式不备份输入 log（容错） | `PRESET`、`LOG`、`OUT_ROOT` | 恒为 0（`|| true`） | 归档目录 |
| `report-no-backup-strict` | 归档模式不备份输入 log（门禁） | `PRESET`、`LOG`、`OUT_ROOT` | 严格检查失败返回非 0 | 归档目录 |
| `demo` | 重建仓库内教学示例产物 | 无 | 恒为 0（`|| true`） | `examples/tma-cute_*` |
| `demo-strict` | 严格模式重建教学示例 | 无 | 严格检查失败返回非 0 | `examples/tma-cute_*` |

## 工作流示例（`cute/default`）

### 1) 环境准备

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project tools/TMA-toolkit
```

### 2) 查看可用 preset

```bash
make -C tools/TMA-toolkit list-presets
```

### 3) 插桩

先预览变更并检查锚点：

```bash
make -C tools/TMA-toolkit apply-dry PRESET=cute/default
```

确认后写入 RTL：

```bash
make -C tools/TMA-toolkit apply PRESET=cute/default
```

可选：打印变量和路径，便于排查参数：

```bash
make -C tools/TMA-toolkit show-vars PRESET=cute/default LOG=log/emu-error.log
```

### 4) 跑仿真

```bash
make run-emu PAYLOAD=<your-payload>
```

### 5) 生成报告

归档模式（容错，命令始终返回 0）：

```bash
make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log
```

归档模式（严格门禁）：

```bash
make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log
```

前缀模式（输出到 `log/`）：

```bash
make -C tools/TMA-toolkit report-prefix PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
```

### 6) 产物说明

默认归档目录：

```text
tools/TMA-toolkit/reports/<module>/<preset>/<run-id>/
```

关键文件：

- `values.csv`：direct + derived + 父子比率
- `combined.png`：分组柱图（含基线虚线）
- `report.md`：人类可读摘要
- `report.rpt`：结构化文本，便于 AI/Agent 读取
- `consistency.json`：一致性检查
- `input.log`：输入日志备份
- `run_meta.json`：本次运行元信息

## Example / Demo（单示例）

仓库内提供了一套扁平 `examples/` 教学样例：

- `examples/emu-error.default.log`（从 `log/emu-error.log` 裁剪，仅保留 `cute/default` direct counters）
- `examples/tma-cute_values.csv`
- `examples/tma-cute_combined.png`
- `examples/tma-cute_report.md`
- `examples/tma-cute_consistency.json`
- `examples/tma-cute_report.rpt`

复现实例命令：

```bash
make -C tools/TMA-toolkit demo
```

说明：`make ... demo` 为容错模式并返回 0；如需门禁语义请使用 `make ... demo-strict`。

示例图：

![TMA 示例图](examples/tma-cute_combined.png)

示例关键结果（来自 `examples/tma-cute_values.csv`）：

- `CUTE_L0_TC_Stall = 83632`
- `L1_Memory = 36537（占 L0 的 43.69%）`
- `L1_Compute = 521（占 L0 的 0.62%）`
- `L1_Dependency = 46574（占 L0 的 55.69%）`
- `L2_Dep_SrcNotReady = 47095`
- `L2_Res_CMLLoadBusy = 26232`
- `L3_Src_By_CML = 37717`

一致性摘要（来自 `examples/tma-cute_consistency.json`）：

- `l1_sum_eq_l0_stall`：PASS
- `l2_sum_eq_l1_dependency`：FAIL（`73327 != 46574`）

## Top-down 读图方法

建议固定顺序：

1. 先看占比
2. 再看绝对值
3. 最后看一致性检查

L0 基线：

- `CUTE_L0_TC_Stall`（图中虚线 `L0 Stall Ref`）

L1 主因：

- `CUTE_L1_TC_Stall_Memory`
- `CUTE_L1_TC_Stall_Compute`
- `CUTE_L1_TC_Stall_Dependency`

L1_Memory 子项：

- `CUTE_L1_TC_Block_AML`
- `CUTE_L1_TC_Block_BML`
- `CUTE_L1_TC_Block_CML`
- `CUTE_L2_Memory_Remain`（残差桶）

L1_Compute 子项：

- `CUTE_L1_TC_Block_ADC`
- `CUTE_L1_TC_Block_BDC`
- `CUTE_L1_TC_Block_CDC`

L1_Dependency 子项（L2）：

- 依赖类：`SrcNotReady / DestBusy / DestHasConsumers / CMLStoreConsumer`
- 资源类：`AMLBusy / BMLBusy / CMLLoadBusy / CMLStoreBusy / ComputeBusy`

L3 来源拆分：

- `SrcNotReady_By_AML/BML/CML/Compute`

## 常见问题与排障

`matplotlib` 缺失：

- 现象：`[ERROR] matplotlib is not installed`
- 处理：`uv sync --project tools/TMA-toolkit`

`report-strict` 失败：

- 现象：命令返回非 0
- 处理：查看 `consistency.json`，按失败项定位口径闭合问题。
- 说明：`make report` 为容错，`make report-strict` 为门禁。

`apply` 锚点未命中：

- 现象：输出出现 `missing_anchors`
- 处理：修改 preset 的 `anchor_regex` 匹配当前 RTL，不要手改插桩块。

输出目录找不到：

- 不传 `--out-prefix`：输出在 `tools/TMA-toolkit/reports/...`
- 传 `--out-prefix`：输出到前缀同目录。

## 扩展到新模块（只改 YAML）

1. 新建 `presets/<module>/<preset>.yaml`
2. 定义 `instrumentation` 与 `analysis`
3. 执行 `apply + report`

```bash
make -C tools/TMA-toolkit apply PRESET=<module>/<preset>
make -C tools/TMA-toolkit report PRESET=<module>/<preset> LOG=<log>
```

原则：

- 工具层保持通用
- 模块差异沉淀在 preset
- 插桩通过工具生成，不手工长期维护

## 命令速查

```bash
make -C tools/TMA-toolkit sync
make -C tools/TMA-toolkit list-presets
make -C tools/TMA-toolkit show-vars PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit apply PRESET=cute/default
make -C tools/TMA-toolkit apply-dry PRESET=cute/default
make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit report-prefix PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
make -C tools/TMA-toolkit report-prefix-strict PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
make -C tools/TMA-toolkit report-no-backup PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit demo
```
