#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import yaml


COUNTER_RE = re.compile(r'XSPerfAccumulate\("([^"]+)"')
BEGIN_RE = re.compile(r"^\s*// BEGIN TMA:([A-Za-z0-9_.-]+)\s*$")
END_RE = re.compile(r"^\s*// END TMA:([A-Za-z0-9_.-]+)\s*$")


@dataclass
class ApplyStats:
    deleted_counters: int = 0
    deleted_imports: int = 0
    inserted_blocks: int = 0
    replaced_blocks: int = 0
    files_changed: Set[str] = field(default_factory=set)
    missing_anchors: List[Tuple[str, str, str]] = field(default_factory=list)


def load_yaml(path: Path) -> dict:
    seen: Set[Path] = set()
    cur = path.resolve()
    while True:
        if cur in seen:
            raise ValueError(f"Cyclic spec redirect detected: {cur}")
        seen.add(cur)

        with cur.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Spec must be a mapping: {cur}")

        redirect_to = data.get("redirect_to")
        has_tma_content = isinstance(data.get("instrumentation"), dict) or isinstance(data.get("analysis"), dict)
        if not isinstance(redirect_to, str) or has_tma_content:
            return data

        nxt = Path(redirect_to)
        if not nxt.is_absolute():
            nxt = (cur.parent / nxt).resolve()
        else:
            nxt = nxt.resolve()
        if not nxt.exists():
            raise FileNotFoundError(f"redirect_to target not found: {redirect_to} (from {cur})")
        cur = nxt


def run_cmd(cmd: Sequence[str], cwd: Optional[Path] = None) -> str:
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}")
    return p.stdout


def parse_added_counters_and_imports(repo_root: Path, baseline_ref: str) -> Tuple[Dict[str, Set[str]], Set[str]]:
    diff = run_cmd(["git", "-C", str(repo_root), "diff", "--unified=0", baseline_ref, "--", "src/main/scala"])
    file_to_added: Dict[str, Set[str]] = {}
    files_with_added_import: Set[str] = set()
    current: Optional[str] = None

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/"):]
            continue
        if current is None:
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue

        payload = line[1:]
        m = COUNTER_RE.search(payload)
        if m:
            file_to_added.setdefault(current, set()).add(m.group(1))
            continue
        if payload.strip() == "import utility.XSPerfAccumulate":
            files_with_added_import.add(current)

    return file_to_added, files_with_added_import


def remove_tma_blocks(text: str, block_ids: Optional[Set[str]] = None) -> Tuple[str, int]:
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    i = 0
    removed = 0
    while i < len(lines):
        m = BEGIN_RE.match(lines[i])
        if not m or (block_ids is not None and m.group(1) not in block_ids):
            out.append(lines[i])
            i += 1
            continue
        bid = m.group(1)
        removed += 1
        i += 1
        while i < len(lines):
            em = END_RE.match(lines[i])
            i += 1
            if em and em.group(1) == bid:
                break
    return "".join(out), removed


def remove_added_counters(text: str, removable_counters: Set[str]) -> Tuple[str, int]:
    if not removable_counters:
        return text, 0
    out: List[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        m = COUNTER_RE.search(line)
        if m and m.group(1) in removable_counters:
            removed += 1
            continue
        out.append(line)
    return "".join(out), removed


def ensure_import_line(text: str, import_line: str) -> str:
    norm = import_line.strip()
    if not norm.startswith("import "):
        norm = f"import {norm}"
    if re.search(rf"^\s*{re.escape(norm)}\s*$", text, flags=re.M):
        return text

    lines = text.splitlines(keepends=True)
    pkg_idx = None
    for i, line in enumerate(lines):
        if line.startswith("package "):
            pkg_idx = i
            break

    if pkg_idx is None:
        return norm + "\n" + text

    insert_idx = pkg_idx + 1
    while insert_idx < len(lines) and lines[insert_idx].strip().startswith("import "):
        insert_idx += 1
    while insert_idx < len(lines) and lines[insert_idx].strip() == "":
        insert_idx += 1

    lines.insert(insert_idx, norm + "\n")
    return "".join(lines)


def remove_import_line(text: str, import_line: str) -> Tuple[str, int]:
    norm = import_line.strip()
    if not norm.startswith("import "):
        norm = f"import {norm}"
    out: List[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if line.strip() == norm:
            removed += 1
            continue
        out.append(line)
    return "".join(out), removed


def render_block(block_id: str, code: str, indent: str = "") -> str:
    code = code.rstrip("\n")
    body = code.splitlines()
    rendered_body = "\n".join((indent + ln if ln else "") for ln in body)
    return f"{indent}// BEGIN TMA:{block_id}\n{rendered_body}\n{indent}// END TMA:{block_id}\n"


def insert_block(text: str, block_id: str, anchor_regex: str, code: str, position: str = "after", indent: str = "") -> Tuple[str, bool]:
    pat = re.compile(anchor_regex, flags=re.M)
    m = pat.search(text)
    if not m:
        return text, False

    block = render_block(block_id, code, indent)
    if position not in {"after", "before"}:
        raise ValueError(f"Invalid block position: {position}")

    if position == "after":
        line_end = text.find("\n", m.end())
        if line_end == -1:
            pos = len(text)
            sep = "\n" if not text.endswith("\n") else ""
            new_text = text + sep + block
        else:
            pos = line_end + 1
            new_text = text[:pos] + block + text[pos:]
    else:
        line_start = text.rfind("\n", 0, m.start())
        pos = 0 if line_start < 0 else line_start + 1
        new_text = text[:pos] + block + text[pos:]
    return new_text, True


def normalize_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def file_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def build_targets(inst: dict) -> List[dict]:
    sites = inst.get("sites")
    points = inst.get("points")
    if isinstance(sites, list) and isinstance(points, list):
        site_map: Dict[str, dict] = {}
        ordered_site_ids: List[str] = []
        for s in sites:
            if not isinstance(s, dict):
                continue
            sid = s.get("id")
            if not sid:
                raise ValueError("instrumentation.sites[].id is required")
            sid = str(sid)
            if sid in site_map:
                raise ValueError(f"Duplicated site id: {sid}")
            if not s.get("file"):
                raise ValueError(f"site {sid} missing file")
            if not s.get("anchor_regex"):
                raise ValueError(f"site {sid} missing anchor_regex")
            site_map[sid] = s
            ordered_site_ids.append(sid)

        lines_by_site: Dict[str, List[str]] = {sid: [] for sid in ordered_site_ids}
        for p in points:
            if not isinstance(p, dict):
                continue
            name = p.get("name")
            expr = p.get("expr")
            sid = p.get("site")
            if not name or not expr or not sid:
                raise ValueError("instrumentation.points[] requires name, expr, site")
            sid = str(sid)
            if sid not in site_map:
                raise ValueError(f"point {name} references unknown site: {sid}")
            lines_by_site[sid].append(f'XSPerfAccumulate("{name}", {expr})')

        targets: List[dict] = []
        for sid in ordered_site_ids:
            s = site_map[sid]
            lines = lines_by_site.get(sid, [])
            if not lines:
                continue
            targets.append(
                {
                    "file": s["file"],
                    "ensure_imports": list(s.get("ensure_imports", [])),
                    "blocks": [
                        {
                            "id": s.get("block_id", f"auto_xsperf_{sid}"),
                            "anchor_regex": s["anchor_regex"],
                            "position": s.get("position", "after"),
                            "indent": s.get("indent", ""),
                            "code": "\n".join(lines),
                        }
                    ],
                }
            )
        return targets

    targets = inst.get("targets", [])
    if not isinstance(targets, list):
        raise ValueError("instrumentation.targets must be a list")
    return targets


def validate_accumulate_only_code(block_id: str, code: str) -> None:
    for idx, line in enumerate(code.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        if not s.startswith('XSPerfAccumulate("'):
            raise ValueError(
                f"accumulate_only policy violation in block {block_id} line {idx}: "
                f"only single-line XSPerfAccumulate statements are allowed"
            )
        if "assert" in s:
            raise ValueError(
                f"accumulate_only policy violation in block {block_id} line {idx}: assert is forbidden"
            )


def apply(spec_path: Path, dry_run: bool, baseline_ref_override: Optional[str], repo_root_override: Optional[str]) -> int:
    spec = load_yaml(spec_path)
    inst = spec.get("instrumentation", {})
    if not isinstance(inst, dict):
        raise ValueError("spec.instrumentation must be a mapping")

    baseline_ref = baseline_ref_override or inst.get("baseline_ref", "origin/master")
    repo_root = Path(repo_root_override or inst.get("repo_root", "XSAI/CUTE")).resolve()

    if not (repo_root / ".git").exists():
        raise RuntimeError(f"repo_root is not a git repository: {repo_root}")

    if not dry_run:
        run_cmd(["git", "-C", str(repo_root), "rev-parse", "--verify", baseline_ref])

    added_map, added_import_files = parse_added_counters_and_imports(repo_root, baseline_ref)

    cleanup_cfg = inst.get("cleanup", {}) or {}
    policy_cfg = inst.get("policy", {}) or {}
    accumulate_only = bool(policy_cfg.get("accumulate_only", False))
    managed_counters = set(inst.get("managed_counters", []))
    remove_all_added = bool(cleanup_cfg.get("remove_all_added", True))

    targets = build_targets(inst)

    block_ids: Set[str] = set()
    target_map: Dict[str, dict] = {}
    for t in targets:
        if not isinstance(t, dict):
            continue
        f = t.get("file")
        if not f:
            continue
        target_map[str(f)] = t
        for b in t.get("blocks", []):
            bid = b.get("id")
            if bid:
                block_ids.add(str(bid))

    files_to_process = set(added_map.keys()) | set(added_import_files) | set(target_map.keys())

    stats = ApplyStats()
    diff_chunks: List[str] = []

    for rel in sorted(files_to_process):
        abs_path = repo_root / rel
        if not abs_path.exists():
            continue

        old_text = abs_path.read_text(encoding="utf-8")
        text = old_text

        text, removed_blocks = remove_tma_blocks(text, None)
        stats.replaced_blocks += removed_blocks

        added_counters = added_map.get(rel, set())
        if remove_all_added:
            removable = set(added_counters)
        else:
            removable = set(c for c in added_counters if c in managed_counters)
        text, removed_cnt = remove_added_counters(text, removable)
        stats.deleted_counters += removed_cnt

        t = target_map.get(rel)
        if t:
            for b in t.get("blocks", []):
                bid = str(b.get("id"))
                anchor = b.get("anchor_regex")
                code = b.get("code", "")
                position = b.get("position", "after")
                indent = b.get("indent", "")
                if not bid or not anchor:
                    continue
                if accumulate_only:
                    validate_accumulate_only_code(bid, str(code))
                text, ok = insert_block(text, bid, anchor, code, position=position, indent=indent)
                if not ok:
                    stats.missing_anchors.append((rel, bid, anchor))
                else:
                    stats.inserted_blocks += 1

            for imp in t.get("ensure_imports", []):
                text = ensure_import_line(text, str(imp))

        if rel in added_import_files and "XSPerfAccumulate(" not in text:
            text, removed_import = remove_import_line(text, "import utility.XSPerfAccumulate")
            stats.deleted_imports += removed_import

        text = normalize_blank_lines(text)

        if text != old_text:
            stats.files_changed.add(rel)
            if dry_run:
                ud = difflib.unified_diff(
                    old_text.splitlines(),
                    text.splitlines(),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                    lineterm="",
                )
                diff_chunks.extend(list(ud))
            else:
                abs_path.write_text(text, encoding="utf-8")

    summary = {
        "repo_root": str(repo_root),
        "baseline_ref": baseline_ref,
        "dry_run": dry_run,
        "files_changed": len(stats.files_changed),
        "changed_files": sorted(stats.files_changed),
        "deleted_counters": stats.deleted_counters,
        "deleted_imports": stats.deleted_imports,
        "inserted_blocks": stats.inserted_blocks,
        "replaced_blocks": stats.replaced_blocks,
        "missing_anchors": [
            {"file": f, "block_id": bid, "anchor_regex": a} for (f, bid, a) in stats.missing_anchors
        ],
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if dry_run and diff_chunks:
        print("\n".join(diff_chunks))

    return 1 if stats.missing_anchors else 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Apply TMA instrumentation to CUTE RTL")
    p.add_argument("--spec", type=Path, required=True, help="Path to TMA spec.yaml")
    p.add_argument("--dry-run", action="store_true", help="Show diff preview without writing files")
    p.add_argument("--baseline-ref", type=str, default=None, help="Override baseline git ref (default from spec)")
    p.add_argument("--repo-root", type=str, default=None, help="Override CUTE repo root (default from spec)")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    return apply(args.spec, args.dry_run, args.baseline_ref, args.repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
