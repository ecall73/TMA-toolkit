MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PRESETS_DIR := $(MAKEFILE_DIR)/presets
REPO_TOP := $(abspath $(MAKEFILE_DIR)/../..)
LOCAL_VENV_PY := $(MAKEFILE_DIR)/.venv/bin/python3
PYTHON ?= $(if $(wildcard $(LOCAL_VENV_PY)),$(LOCAL_VENV_PY),python3)

PRESET ?= cute/default
SPEC ?=
LOG ?= $(MAKEFILE_DIR)/../../log/emu-error.log
OUT_ROOT ?= $(MAKEFILE_DIR)/reports
RUN_ID ?=
BASELINE_REF ?= origin/master
REPO_ROOT ?= $(REPO_TOP)/XSAI/CUTE

SPEC_ARG = $(if $(SPEC),--spec $(SPEC),--preset $(PRESET))
RUN_ID_ARG = $(if $(RUN_ID),--run-id $(RUN_ID),)
LOG_ARG = $(if $(filter /%,$(LOG)),$(LOG),$(REPO_TOP)/$(LOG))

.PHONY: help list-presets apply apply-dry report report-strict

help:
	@echo "TMA-toolkit Make Targets"
	@echo "  make -C tools/TMA-toolkit list-presets"
	@echo "  make -C tools/TMA-toolkit apply PRESET=cute/default"
	@echo "  make -C tools/TMA-toolkit apply-dry PRESET=cute/default"
	@echo "  make -C tools/TMA-toolkit report PRESET=cute/default LOG=log/emu-error.log"
	@echo "  make -C tools/TMA-toolkit report-strict PRESET=cute/default LOG=log/emu-error.log"
	@echo ""
	@echo "Variables: PRESET, SPEC, LOG, OUT_ROOT, RUN_ID, BASELINE_REF, REPO_ROOT"

list-presets:
	@cd $(PRESETS_DIR) && find . -type f -name '*.yaml' | sort | sed 's#^./##; s#\.yaml$$##'

apply:
	$(PYTHON) $(MAKEFILE_DIR)/tma.py apply $(SPEC_ARG) --baseline-ref $(BASELINE_REF) --repo-root $(REPO_ROOT)

apply-dry:
	$(PYTHON) $(MAKEFILE_DIR)/tma.py apply $(SPEC_ARG) --dry-run --baseline-ref $(BASELINE_REF) --repo-root $(REPO_ROOT)

report:
	$(PYTHON) $(MAKEFILE_DIR)/tma.py report $(SPEC_ARG) --log $(LOG_ARG) --out-root $(OUT_ROOT) $(RUN_ID_ARG) || true

report-strict:
	$(PYTHON) $(MAKEFILE_DIR)/tma.py report $(SPEC_ARG) --log $(LOG_ARG) --out-root $(OUT_ROOT) $(RUN_ID_ARG) --strict
