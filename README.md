# TMA-toolkit (Top-down Micro-architecture Analysis)

`tools/TMA-toolkit` is a module-agnostic toolchain:
- `apply`: insert/remove `XSPerfAccumulate(...)` counters from YAML preset
- `report`: parse log and generate CSV/PNG/MD/JSON from the same preset

## Layout

- `tools/TMA-toolkit/tma.py`: CLI entry
- `tools/TMA-toolkit/tma_apply.py`: instrumentation engine
- `tools/TMA-toolkit/tma_report.py`: report engine
- `tools/TMA-toolkit/presets/<module>/<preset>.yaml`: module presets
- `tools/TMA-toolkit/reports/`: archived reports
- `tools/TMA-toolkit/Makefile`: unified entrypoints

Current default preset:
- `cute/default` -> `tools/TMA-toolkit/presets/cute/default.yaml`
- `cute/legacy_27ac003_4cdc89a` -> `tools/TMA-toolkit/presets/cute/legacy_27ac003_4cdc89a.yaml`

Additional docs:
- Chinese README: `tools/TMA-toolkit/README.zh-CN.md`
- AI usage guide: `tools/TMA-toolkit/SKILL.md`

## Quick Start

### 0) Optional local Python env (recommended for plotting)

```bash
python3 -m venv tools/TMA-toolkit/.venv
tools/TMA-toolkit/.venv/bin/pip install matplotlib pyyaml
```

### Apply instrumentation

```bash
python3 tools/TMA-toolkit/tma.py apply --preset cute/default
```

### Run simulation

```bash
make run-emu PAYLOAD=<your-payload>
```

### Generate report from log

```bash
python3 tools/TMA-toolkit/tma.py report \
  --preset cute/default \
  --log log/emu-error.log
```

Legacy baseline (for `dev/cute_tma` commits `27ac003` + `4cdc89a`):

```bash
python3 tools/TMA-toolkit/tma.py apply --preset cute/legacy_27ac003_4cdc89a --dry-run
python3 tools/TMA-toolkit/tma.py report \
  --preset cute/legacy_27ac003_4cdc89a \
  --log log/emu-error.base.log \
  --out-prefix log/cute-counter-graph-legacy
```

## Makefile Workflow

```bash
make -C tools/TMA-toolkit list-presets
make -C tools/TMA-toolkit apply PRESET=cute/default
make -C tools/TMA-toolkit apply-dry PRESET=cute/default
make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log
```

Variables:
- `PRESET` default `cute/default`
- `LOG` default `../../log/emu-error.log` (relative to `tools/TMA-toolkit/Makefile`)
- `OUT_ROOT` default `tools/TMA-toolkit/reports`
- `RUN_ID` optional (default timestamp)
- `BASELINE_REF` / `REPO_ROOT` for `apply`
- `PYTHON` optional override; by default Makefile uses `tools/TMA-toolkit/.venv/bin/python3` if it exists, otherwise `python3`

## Report Archive

Each run is written to:

```text
tools/TMA-toolkit/reports/<module>/<preset>/<run-id>/
```

Generated files:
- `values.csv`
- `combined.png`
- `report.md`
- `consistency.json`
- `input.log` (default backup on)
- `run_meta.json`

## CUTE Default Preset Notes

- L1 uses exclusive `Memory / Compute / Dependency`.
- `ReleasePendingStore` is **not** a direct counter.
- L1 memory child uses residual bucket:
  - `CUTE_L2_Memory_Remain = L1_Memory - AML - BML - CML`

## CUTE Legacy Preset Notes

- L1 uses nonexclusive `Memory / Compute / Schedule`.
- It restores `CUTE_L2_TC_*` + `CUTE_L3_SB_*` + `CUTE_L3_ML_*` + `CUTE_L3_DC_*` hierarchy and chart layout used by legacy baseline reports.

## Add New Module

1. Add a preset under `tools/TMA-toolkit/presets/<module>/<preset>.yaml`.
2. Define both `instrumentation` and `analysis`.
3. Run:

```bash
python3 tools/TMA-toolkit/tma.py apply --preset <module>/<preset>
python3 tools/TMA-toolkit/tma.py report --preset <module>/<preset> --log <log>
```
