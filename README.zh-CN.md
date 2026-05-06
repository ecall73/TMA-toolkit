# TMA-toolkit（Top-down Micro-architecture Analysis）

`tools/TMA-toolkit` 是一个与模块解耦的性能分析工具链：
- `apply`：根据 YAML preset 自动插入/刷新 `XSPerfAccumulate(...)` 插桩
- `report`：根据同一份 YAML + 仿真日志生成 `CSV/PNG/Markdown/JSON` 报告

## 目录结构

- `tools/TMA-toolkit/tma.py`：统一 CLI 入口
- `tools/TMA-toolkit/tma_apply.py`：插桩引擎
- `tools/TMA-toolkit/tma_report.py`：日志解析与报告引擎
- `tools/TMA-toolkit/presets/<module>/<preset>.yaml`：模块化 preset
- `tools/TMA-toolkit/reports/`：归档报告目录
- `tools/TMA-toolkit/Makefile`：统一命令入口

当前常用 preset：
- `cute/default`：当前 CUTE 口径（L1: Memory/Compute/Dependency）
- `cute/legacy_27ac003_4cdc89a`：历史 legacy 口径（nonexclusive）

## 快速开始

### 0) 可选：创建本地 Python 环境（建议）

```bash
python3 -m venv tools/TMA-toolkit/.venv
tools/TMA-toolkit/.venv/bin/pip install matplotlib pyyaml
```

### 1) 插桩

```bash
python3 tools/TMA-toolkit/tma.py apply --preset cute/default
```

legacy 口径示例：

```bash
python3 tools/TMA-toolkit/tma.py apply --preset cute/legacy_27ac003_4cdc89a
```

### 2) 运行仿真（由现有流程负责）

```bash
make run-emu PAYLOAD=<your-payload>
```

### 3) 生成报告

归档模式（推荐，输出到 `tools/TMA-toolkit/reports`）：

```bash
python3 tools/TMA-toolkit/tma.py report \
  --preset cute/default \
  --log log/emu-error.log
```

兼容模式（输出到指定前缀，比如 `log/`）：

```bash
python3 tools/TMA-toolkit/tma.py report \
  --preset cute/legacy_27ac003_4cdc89a \
  --log log/emu-error.base.log \
  --out-prefix log/cute-counter-graph-legacy
```

## Makefile 用法

```bash
make -C tools/TMA-toolkit help
make -C tools/TMA-toolkit list-presets
make -C tools/TMA-toolkit apply PRESET=cute/default
make -C tools/TMA-toolkit apply-dry PRESET=cute/default
make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log
```

常用变量：
- `PRESET`：默认 `cute/default`
- `LOG`：默认 `../../log/emu-error.log`（相对 `tools/TMA-toolkit/Makefile`）
- `OUT_ROOT`：默认 `tools/TMA-toolkit/reports`
- `RUN_ID`：可选，不传则自动时间戳
- `BASELINE_REF` / `REPO_ROOT`：`apply` 阶段使用
- `PYTHON`：可选，默认优先使用 `tools/TMA-toolkit/.venv/bin/python3`

## 报告归档目录

不使用 `--out-prefix` 时，报告会归档到：

```text
tools/TMA-toolkit/reports/<module>/<preset>/<run-id>/
```

文件包括：
- `values.csv`
- `combined.png`
- `report.md`
- `consistency.json`
- `input.log`（默认备份）
- `run_meta.json`

## 新增模块支持

只需新增一个 preset 文件，无需改工具代码：

1. 新建 `tools/TMA-toolkit/presets/<module>/<preset>.yaml`
2. 在 YAML 中定义 `instrumentation` 与 `analysis`
3. 直接执行 `apply + report`

