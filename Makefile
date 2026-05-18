MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PRESETS_DIR := $(MAKEFILE_DIR)/presets
REPO_TOP := $(abspath $(MAKEFILE_DIR)/../..)
UV ?= uv
UV_RUN := $(UV) run --project $(MAKEFILE_DIR)

PRESET ?= cute/default
LOG ?= $(MAKEFILE_DIR)/../../log/emu-error.log
OUT_ROOT ?= $(MAKEFILE_DIR)/reports
OUT_PREFIX ?=
RUN_ID ?=
BASELINE_REF ?= origin/master
REPO_ROOT ?= $(REPO_TOP)/XSAI/CUTE
BACKUP_LOG ?= 1

RUN_ID_ARG = $(if $(RUN_ID),--run-id $(RUN_ID),)
LOG_ARG = $(if $(filter /%,$(LOG)),$(LOG),$(REPO_TOP)/$(LOG))
OUT_PREFIX_ARG = $(if $(OUT_PREFIX),--out-prefix $(if $(filter /%,$(OUT_PREFIX)),$(OUT_PREFIX),$(REPO_TOP)/$(OUT_PREFIX)),)
BACKUP_LOG_ARG = $(if $(filter 0,$(BACKUP_LOG)),--no-backup-log,--backup-log)
EXAMPLE_LOG := $(MAKEFILE_DIR)/examples/emu-error.default.log
EXAMPLE_PREFIX := $(MAKEFILE_DIR)/examples/tma-cute

.PHONY: help check-uv sync list-presets show-vars apply apply-dry report report-strict report-prefix report-prefix-strict report-no-backup report-no-backup-strict demo demo-strict

help:
	@echo "TMA-toolkit Make Targets"
	@echo "  make -C tools/TMA-toolkit sync"
	@echo "      Install/update project dependencies via uv lockfile."
	@echo "  make -C tools/TMA-toolkit list-presets"
	@echo "      List available preset ids under presets/."
	@echo "  make -C tools/TMA-toolkit show-vars"
	@echo "      Print effective variables and resolved paths for this run."
	@echo "  make -C tools/TMA-toolkit apply PRESET=cute/default"
	@echo "      Write instrumentation into RTL files."
	@echo "  make -C tools/TMA-toolkit apply-dry PRESET=cute/default"
	@echo "      Preview instrumentation changes without editing files."
	@echo "  make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log"
	@echo "      Archive report mode (tolerant): generate HTML/RPT/JSON and always return zero."
	@echo "  make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log"
	@echo "      Archive report mode (strict gate): generate HTML/RPT/JSON and return non-zero on failures."
	@echo "  make -C tools/TMA-toolkit report-prefix PRESET=cute/default LOG=... OUT_PREFIX=log/tma-cute"
	@echo "      Prefix output mode (tolerant): generate <prefix>_report.html/.rpt/_consistency.json."
	@echo "  make -C tools/TMA-toolkit report-prefix-strict PRESET=cute/default LOG=... OUT_PREFIX=log/tma-cute"
	@echo "      Prefix output mode (strict gate): generate <prefix>_report.html/.rpt/_consistency.json."
	@echo "  make -C tools/TMA-toolkit report-no-backup PRESET=cute/default LOG=..."
	@echo "      Archive report (compat target): no input-log backup in new HTML flow."
	@echo "  make -C tools/TMA-toolkit report-no-backup-strict PRESET=cute/default LOG=..."
	@echo "      Archive report strict (compat target): no input-log backup in new HTML flow."
	@echo "  make -C tools/TMA-toolkit demo"
	@echo "      Re-generate the single teaching example bundle under examples/."
	@echo "  make -C tools/TMA-toolkit demo-strict"
	@echo "      Same as demo but strict gate mode."
	@echo ""
	@echo "Variables: PRESET, LOG, OUT_ROOT, OUT_PREFIX, RUN_ID, BASELINE_REF, REPO_ROOT, BACKUP_LOG"
	@echo ""
	@echo "If uv is missing, install without sudo:"
	@echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"

check-uv:
	@command -v $(UV) >/dev/null 2>&1 || { \
		echo "[ERROR] uv is not installed or not in PATH"; \
		echo "        Install without sudo:"; \
		echo "        curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 2; \
	}

sync: check-uv
	$(UV) sync --project $(MAKEFILE_DIR)

list-presets:
	@cd $(PRESETS_DIR) && find . -type f -name '*.yaml' | sort | sed 's#^./##; s#\.yaml$$##'

show-vars:
	@echo "PRESET=$(PRESET)"
	@echo "LOG=$(LOG)"
	@echo "LOG_ARG=$(LOG_ARG)"
	@echo "OUT_ROOT=$(OUT_ROOT)"
	@echo "OUT_PREFIX=$(OUT_PREFIX)"
	@echo "OUT_PREFIX_ARG=$(OUT_PREFIX_ARG)"
	@echo "RUN_ID=$(RUN_ID)"
	@echo "BASELINE_REF=$(BASELINE_REF)"
	@echo "REPO_ROOT=$(REPO_ROOT)"
	@echo "BACKUP_LOG=$(BACKUP_LOG)"
	@echo "BACKUP_LOG_ARG=$(BACKUP_LOG_ARG)"

apply: check-uv
	$(UV_RUN) tma-toolkit apply --preset $(PRESET) --baseline-ref $(BASELINE_REF) --repo-root $(REPO_ROOT)

apply-dry: check-uv
	$(UV_RUN) tma-toolkit apply --preset $(PRESET) --dry-run --baseline-ref $(BASELINE_REF) --repo-root $(REPO_ROOT)

report: check-uv
	$(UV_RUN) tma-toolkit report --preset $(PRESET) --log $(LOG_ARG) --out-root $(OUT_ROOT) $(RUN_ID_ARG) $(BACKUP_LOG_ARG) || true

report-strict: check-uv
	$(UV_RUN) tma-toolkit report --preset $(PRESET) --log $(LOG_ARG) --out-root $(OUT_ROOT) $(RUN_ID_ARG) $(BACKUP_LOG_ARG) --strict

report-prefix: check-uv
	@test -n "$(OUT_PREFIX)" || { echo "[ERROR] OUT_PREFIX is required"; exit 2; }
	$(UV_RUN) tma-toolkit report --preset $(PRESET) --log $(LOG_ARG) $(OUT_PREFIX_ARG) || true

report-prefix-strict: check-uv
	@test -n "$(OUT_PREFIX)" || { echo "[ERROR] OUT_PREFIX is required"; exit 2; }
	$(UV_RUN) tma-toolkit report --preset $(PRESET) --log $(LOG_ARG) $(OUT_PREFIX_ARG) --strict

report-no-backup: check-uv
	$(UV_RUN) tma-toolkit report --preset $(PRESET) --log $(LOG_ARG) --out-root $(OUT_ROOT) $(RUN_ID_ARG) --no-backup-log || true

report-no-backup-strict: check-uv
	$(UV_RUN) tma-toolkit report --preset $(PRESET) --log $(LOG_ARG) --out-root $(OUT_ROOT) $(RUN_ID_ARG) --no-backup-log --strict

demo: check-uv
	$(UV_RUN) tma-toolkit report --preset cute/default --log $(EXAMPLE_LOG) --out-prefix $(EXAMPLE_PREFIX) || true

demo-strict: check-uv
	$(UV_RUN) tma-toolkit report --preset cute/default --log $(EXAMPLE_LOG) --out-prefix $(EXAMPLE_PREFIX) --strict
