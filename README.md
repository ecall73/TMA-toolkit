# TMA-toolkit (Top-down Micro-architecture Analysis)

Chinese version: [README.zh-CN.md](README.zh-CN.md)

`tools/TMA-toolkit` is a YAML-driven toolkit for:

- `apply`: insert/refresh `XSPerfAccumulate(...)` from preset
- `report`: parse simulation log and generate **HTML + RPT + consistency JSON**

## Output Contract

Report outputs are now:

- `report.html` (main human-readable visualization, multi-tab)
- `report.rpt` (structured pseudo-graphic text for AI/agent)
- `consistency.json` (strict-check debug artifact)

The old `CSV/PNG/MD` report artifacts are no longer generated.

## Quick Start

### 1) Environment

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project tools/TMA-toolkit
```

### 2) List presets

```bash
make -C tools/TMA-toolkit list-presets
```

### 3) Instrumentation

```bash
make -C tools/TMA-toolkit apply-dry PRESET=cute/default
make -C tools/TMA-toolkit apply PRESET=cute/default
```

### 4) Report generation

Archive mode:

```bash
make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log
make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log
```

Prefix mode:

```bash
make -C tools/TMA-toolkit report-prefix PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
make -C tools/TMA-toolkit report-prefix-strict PRESET=cute/default LOG=log/emu-error.log OUT_PREFIX=log/tma-cute
```

## Paths and Filenames

### Archive mode

```text
tools/TMA-toolkit/reports/<module>/<preset>/<run-id>/
  report.html
  report.rpt
  consistency.json
```

### Prefix mode

```text
<OUT_PREFIX>_report.html
<OUT_PREFIX>_report.rpt
<OUT_PREFIX>_consistency.json
```

## HTML Report Layout

The HTML report follows the RedLeaves-style multi-tab interaction with 4 tabs:

1. `Overview`: meta, key metrics, direct/derived counters
2. `Breakdown`: hierarchy tree + chart-group table + ratio rows
3. `Charts`: interactive Plotly charts (group breakdown + top contributors)
4. `Consistency`: checks and diagnostic notes

Plotly is loaded via CDN (`include_plotlyjs='cdn'`).

## Built-in Presets

- `cute/default`
- `cute/legacy_v1`
- `cute/matrix_hpm_sim_report` (report-only preset for `MAT_SIM_*`)

## Example Flows

### A) Default teaching sample (`examples/`)

```bash
make -C tools/TMA-toolkit demo
```

Generates:

- `tools/TMA-toolkit/examples/tma-cute_report.html`
- `tools/TMA-toolkit/examples/tma-cute_report.rpt`
- `tools/TMA-toolkit/examples/tma-cute_consistency.json`

### B) HPM sim sample (use repo log directly)

```bash
make -C tools/TMA-toolkit report-prefix-strict \
  PRESET=cute/matrix_hpm_sim_report \
  LOG=log/emu-error.log \
  OUT_PREFIX=tools/TMA-toolkit/reports/cute/matrix_hpm_sim_report/latest
```

Generates:

- `.../latest_report.html`
- `.../latest_report.rpt`
- `.../latest_consistency.json`

## Make Targets

Use `make -C tools/TMA-toolkit help` for full descriptions.

Core targets:

- `sync`
- `list-presets`
- `show-vars`
- `apply`, `apply-dry`
- `report`, `report-strict`
- `report-prefix`, `report-prefix-strict`
- `report-no-backup`, `report-no-backup-strict` (compat targets)
- `demo`, `demo-strict`

## Strict Mode Semantics

- `report*` tolerant variants return zero (`|| true` in Makefile wrappers).
- `*-strict` variants return non-zero when any `error` severity consistency check fails.

## Troubleshooting

### `plotly` missing

```bash
uv sync --project tools/TMA-toolkit
```

### `apply` missing anchors

- Update preset `anchor_regex` for current RTL.
- Do not hand-edit generated instrumentation blocks.

### Strict report failed

- Check `consistency.json` and `report.rpt` first.
- Failure often indicates semantic mismatch, not tool crash.

## Design Rules

- Keep module semantics in preset YAML.
- Keep toolkit generic and reusable.
- Prefer changing preset over hard-coding module behavior in Python.
- Use `apply` automation, avoid long-lived manual instrumentation edits.
