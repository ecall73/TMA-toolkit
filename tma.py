#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

from tma_apply import apply as apply_impl
from tma_report import plt, run_report


def _tool_dir() -> Path:
    return Path(__file__).resolve().parent


def _presets_root() -> Path:
    return _tool_dir() / "presets"


def _resolve_preset(preset: str) -> Tuple[Path, str]:
    rel = preset.strip().strip("/")
    rel_path = Path(rel)
    if rel_path.suffix != ".yaml":
        rel_path = rel_path.with_suffix(".yaml")
    spec_path = (_presets_root() / rel_path).resolve()
    if not spec_path.exists():
        raise FileNotFoundError(f"Preset not found: {preset} -> {spec_path}")
    preset_id = str(rel_path.with_suffix("")).replace("\\", "/")
    return spec_path, preset_id


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TMA tool (preset-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ap = sub.add_parser("apply", help="Apply/refresh RTL instrumentation")
    ap.add_argument("--preset", type=str, required=True, help="Preset under tools/TMA-toolkit/presets, e.g. cute/default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--baseline-ref", type=str, default=None)
    ap.add_argument("--repo-root", type=str, default=None)

    rp = sub.add_parser("report", help="Generate report from log + preset")
    rp.add_argument("--preset", type=str, required=True, help="Preset under tools/TMA-toolkit/presets, e.g. cute/default")
    rp.add_argument("--log", type=Path, required=True)
    rp.add_argument("--out-prefix", type=Path, help="Output prefix mode")
    rp.add_argument("--out-root", type=Path, default=_tool_dir() / "reports", help="Archive root when --out-prefix is omitted")
    rp.add_argument("--run-id", type=str, default=None, help="Archive run id; default is timestamp")
    rp.add_argument("--backup-log", dest="backup_log", action="store_true", default=True, help="Backup input log in archive directory (default)")
    rp.add_argument("--no-backup-log", dest="backup_log", action="store_false", help="Do not backup input log")
    rp.add_argument("--strict", action="store_true")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "apply":
            spec_path, _ = _resolve_preset(args.preset)
            return apply_impl(spec_path, args.dry_run, args.baseline_ref, args.repo_root)
        if args.cmd == "report":
            if plt is None:
                print("[ERROR] matplotlib is not installed. Please install it first:", file=sys.stderr)
                print("        uv sync --project tools/TMA-toolkit", file=sys.stderr)
                return 2
            spec_path, preset_id = _resolve_preset(args.preset)
            return run_report(
                spec_path=spec_path,
                log_path=args.log.resolve(),
                out_prefix=args.out_prefix.resolve() if args.out_prefix else None,
                strict=args.strict,
                out_root=args.out_root.resolve() if args.out_root else None,
                run_id=args.run_id,
                backup_log=args.backup_log,
                preset_id=preset_id,
                cli_args=list(argv) if argv is not None else list(sys.argv[1:]),
            )
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2
    print(f"Unknown cmd: {args.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
