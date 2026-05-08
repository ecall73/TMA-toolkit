#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import json
import math
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import yaml

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover
    plt = None


class SafeEvalError(Exception):
    pass


class SafeExprEvaluator(ast.NodeVisitor):
    _allowed_binops = (ast.Add, ast.Sub, ast.Mult, ast.Div)
    _allowed_unary = (ast.UAdd, ast.USub)
    _allowed_cmp = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)

    def __init__(self, env: Mapping[str, float]):
        self.env = env

    def visit_Expression(self, node: ast.Expression):
        return self.visit(node.body)

    def visit_Name(self, node: ast.Name):
        if node.id not in self.env:
            raise SafeEvalError(f"Unknown symbol: {node.id}")
        return self.env[node.id]

    def visit_Constant(self, node: ast.Constant):
        if not isinstance(node.value, (int, float, bool)):
            raise SafeEvalError(f"Invalid constant: {node.value!r}")
        return node.value

    def visit_BinOp(self, node: ast.BinOp):
        if not isinstance(node.op, self._allowed_binops):
            raise SafeEvalError(f"Unsupported operator: {ast.dump(node.op)}")
        l = float(self.visit(node.left))
        r = float(self.visit(node.right))
        if isinstance(node.op, ast.Add):
            return l + r
        if isinstance(node.op, ast.Sub):
            return l - r
        if isinstance(node.op, ast.Mult):
            return l * r
        if isinstance(node.op, ast.Div):
            return l / r if r != 0 else math.nan
        raise SafeEvalError("unreachable")

    def visit_UnaryOp(self, node: ast.UnaryOp):
        if not isinstance(node.op, self._allowed_unary):
            raise SafeEvalError(f"Unsupported unary op: {ast.dump(node.op)}")
        v = float(self.visit(node.operand))
        return +v if isinstance(node.op, ast.UAdd) else -v

    def visit_Compare(self, node: ast.Compare):
        left = float(self.visit(node.left))
        ok = True
        cur = left
        for op, cmp_node in zip(node.ops, node.comparators):
            if not isinstance(op, self._allowed_cmp):
                raise SafeEvalError(f"Unsupported compare: {ast.dump(op)}")
            right = float(self.visit(cmp_node))
            if isinstance(op, ast.Eq):
                ok = ok and (cur == right)
            elif isinstance(op, ast.NotEq):
                ok = ok and (cur != right)
            elif isinstance(op, ast.Lt):
                ok = ok and (cur < right)
            elif isinstance(op, ast.LtE):
                ok = ok and (cur <= right)
            elif isinstance(op, ast.Gt):
                ok = ok and (cur > right)
            elif isinstance(op, ast.GtE):
                ok = ok and (cur >= right)
            cur = right
        return ok

    def visit_BoolOp(self, node: ast.BoolOp):
        vals = [bool(self.visit(v)) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals)
        if isinstance(node.op, ast.Or):
            return any(vals)
        raise SafeEvalError(f"Unsupported bool op: {ast.dump(node.op)}")

    def generic_visit(self, node: ast.AST):
        raise SafeEvalError(f"Unsupported syntax: {ast.dump(node)}")


def eval_expr(expr: str, env: Mapping[str, float]):
    try:
        tree = ast.parse(expr, mode="eval")
        return SafeExprEvaluator(env).visit(tree)
    except Exception:
        return math.nan


@dataclass
class ParseResult:
    counters: Dict[str, float]
    last_time: Optional[int]


def load_spec(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Spec must be mapping")
    return data


def resolve_analysis(spec: dict) -> dict:
    ana = spec.get("analysis")
    if isinstance(ana, dict):
        return ana
    return spec


def collect_direct_names(spec: dict, ana: dict) -> List[str]:
    direct = ana.get("direct_counters", [])
    if isinstance(direct, list) and direct:
        return [str(x) for x in direct]
    inst = spec.get("instrumentation", {})
    points = inst.get("points", []) if isinstance(inst, dict) else []
    names: List[str] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if name:
            names.append(str(name))
    return names


def parse_log(log_path: Path, parse_cfg: dict, direct_set: set) -> ParseResult:
    pattern = parse_cfg.get("line_regex")
    if not pattern:
        raise ValueError("analysis.parse.line_regex is required")
    regex = re.compile(pattern)
    use_last = bool(parse_cfg.get("use_last_occurrence", True))
    keep_declared = bool(parse_cfg.get("keep_only_declared_direct_counters", True))

    counters: Dict[str, float] = {}
    last_time = None
    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = regex.match(line.rstrip("\n"))
            if not m:
                continue
            name = m.group("name")
            if keep_declared and name not in direct_set:
                continue
            value = float(m.group("value"))
            t = int(m.group("time")) if "time" in m.groupdict() else None
            if use_last or name not in counters:
                counters[name] = value
                if t is not None:
                    last_time = t
    return ParseResult(counters, last_time)


def derive(direct_order: Sequence[str], parsed: Mapping[str, float], formulas: Mapping[str, str]) -> Dict[str, float]:
    env: Dict[str, float] = {}
    for name in direct_order:
        env[name] = parsed.get(name, math.nan)
    derived: Dict[str, float] = {}
    for name, expr in formulas.items():
        v = eval_expr(expr, env)
        try:
            v = float(v)
        except Exception:
            v = math.nan
        derived[name] = v
        env[name] = v
    return derived


def compute_checks(values: Mapping[str, float], checks: Sequence[dict]) -> List[dict]:
    out = []
    env = dict(values)
    for c in checks:
        name = c.get("name", "unnamed")
        passed = False
        detail = ""
        if "expr" in c:
            r = eval_expr(str(c["expr"]), env)
            passed = bool(r) if isinstance(r, bool) else bool(r and not math.isnan(float(r)))
            detail = f"expr={c['expr']}"
        else:
            lhs_expr = str(c.get("lhs", "nan"))
            rhs_expr = str(c.get("rhs", "nan"))
            lhs = eval_expr(lhs_expr, env)
            rhs = eval_expr(rhs_expr, env)
            try:
                lhs = float(lhs)
                rhs = float(rhs)
                tol = float(c.get("tolerance", 0.0))
                diff = abs(lhs - rhs)
                passed = (not math.isnan(diff)) and diff <= tol
                detail = f"lhs={lhs} rhs={rhs} diff={diff} tol={tol}"
            except Exception:
                passed = False
                detail = f"lhs={lhs_expr} rhs={rhs_expr} eval_failed"
        out.append({"name": name, "passed": passed, "detail": detail, "severity": c.get("severity", "error")})
    return out


def apply_missing_direct_fallback(
    values: MutableMapping[str, float],
    missing_direct: Sequence[str],
    fallback_cfg: Mapping[str, str],
) -> Dict[str, str]:
    used: Dict[str, str] = {}
    for name in missing_direct:
        expr = fallback_cfg.get(name)
        if not isinstance(expr, str) or not expr.strip():
            continue
        v = eval_expr(expr, values)
        try:
            fv = float(v)
        except Exception:
            continue
        if math.isnan(fv):
            continue
        values[name] = fv
        used[name] = expr
    return used


def is_finite_number(v: float) -> bool:
    try:
        return math.isfinite(float(v))
    except Exception:
        return False


def compute_ratio(numerator: float, denominator: float) -> float:
    if not is_finite_number(numerator) or not is_finite_number(denominator):
        return math.nan
    denom = float(denominator)
    if denom == 0.0:
        return math.nan
    return float(numerator) / denom


def format_ratio(v: float, decimals: int) -> str:
    if not is_finite_number(v):
        return "NaN"
    return f"{float(v):.{decimals}f}"


def build_hierarchy_parent_map(hierarchy: Sequence[dict]) -> Dict[str, str]:
    parent_of: Dict[str, str] = {}
    for rel in hierarchy:
        if not isinstance(rel, dict):
            continue
        parent = rel.get("parent")
        if not parent:
            continue
        for child in rel.get("children", []):
            child_name = str(child)
            if child_name not in parent_of:
                parent_of[child_name] = str(parent)
    return parent_of


def build_group_ratio_parent_map(groups: Sequence[dict]) -> Dict[str, str]:
    parent_of: Dict[str, str] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        default_parent = group.get("ratio_parent")
        per_counter_parent = group.get("ratio_parent_map", {})
        counters = group.get("counters", [])
        if isinstance(default_parent, str):
            for c in counters:
                counter = str(c)
                if counter not in parent_of:
                    parent_of[counter] = default_parent
        if isinstance(per_counter_parent, dict):
            for counter, parent in per_counter_parent.items():
                counter_name = str(counter)
                if counter_name not in parent_of and isinstance(parent, str):
                    parent_of[counter_name] = parent
    return parent_of


def collect_ratio_rows(values: Mapping[str, float], hierarchy: Sequence[dict], groups: Sequence[dict]) -> List[Tuple[str, str, float]]:
    rows: List[Tuple[str, str, float]] = []
    seen: Set[Tuple[str, str]] = set()

    def add(counter: str, parent: str):
        key = (counter, parent)
        if key in seen:
            return
        seen.add(key)
        ratio = compute_ratio(values.get(counter, math.nan), values.get(parent, math.nan))
        rows.append((counter, parent, ratio))

    for rel in hierarchy:
        if not isinstance(rel, dict):
            continue
        parent = rel.get("parent")
        if not parent:
            continue
        parent_name = str(parent)
        for child in rel.get("children", []):
            add(str(child), parent_name)

    hierarchy_parent = build_hierarchy_parent_map(hierarchy)
    for group in groups:
        if not isinstance(group, dict):
            continue
        parent = group.get("ratio_parent")
        if not isinstance(parent, str):
            continue
        for child in group.get("counters", []):
            child_name = str(child)
            if child_name in hierarchy_parent:
                continue
            add(child_name, parent)

    return rows


def write_csv(
    path: Path,
    direct_names: Sequence[str],
    parsed: Mapping[str, float],
    derived: Mapping[str, float],
    formulas: Mapping[str, str],
    ratios: Sequence[Tuple[str, str, float]],
    resolved_values: Mapping[str, float],
    fallback_used: Mapping[str, str],
):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["row_type", "counter", "kind", "value", "formula", "parent", "ratio_in_parent"])
        for n in direct_names:
            kind = "direct_fallback" if n in fallback_used else "direct"
            formula = fallback_used.get(n, "")
            w.writerow(["counter", n, kind, resolved_values.get(n, parsed.get(n, math.nan)), formula, "", ""])

        emitted_derived: Set[str] = set()
        for name, formula in formulas.items():
            emitted_derived.add(str(name))
            w.writerow(["counter", name, "derived", derived.get(name, math.nan), formula, "", ""])
        for name, value in derived.items():
            if name in emitted_derived:
                continue
            w.writerow(["counter", name, "derived", value, "", "", ""])

        for counter, parent, ratio in ratios:
            w.writerow(["ratio", counter, "ratio", resolved_values.get(counter, math.nan), "", parent, ratio])


def short_label(name: str, aliases: Mapping[str, str]) -> str:
    if name in aliases:
        return aliases[name]
    return name


def plot(
    values: Mapping[str, float],
    groups: Sequence[dict],
    aliases: Mapping[str, str],
    hierarchy: Sequence[dict],
    plot_cfg: Mapping[str, object],
    out: Path,
):
    if plt is None:
        raise RuntimeError("matplotlib is not installed")
    from matplotlib.patches import Rectangle

    title = str(plot_cfg.get("title", "CUTE Counters (Value; ratio shown above each bar)"))
    group_gap = float(plot_cfg.get("group_gap", 1.0))
    bar_width = float(plot_cfg.get("bar_width", 0.75))
    bar_color = str(plot_cfg.get("bar_color", "#4C78A8"))
    bar_alpha = float(plot_cfg.get("bar_alpha", 0.85))
    ratio_color = str(plot_cfg.get("ratio_color", "#F57C00"))
    ratio_decimals = int(plot_cfg.get("ratio_decimals", 3))
    major_sep_color = str(plot_cfg.get("major_separator_color", "#A0A0A0"))
    major_sep_alpha = float(plot_cfg.get("major_separator_alpha", 0.6))
    subgroup_sep_color = str(plot_cfg.get("subgroup_separator_color", "#8D8D8D"))
    subgroup_sep_alpha = float(plot_cfg.get("subgroup_separator_alpha", 0.9))
    baseline_counter = str(plot_cfg.get("baseline_counter", "CUTE_L0_TC_Stall"))
    baseline_label = str(plot_cfg.get("baseline_label", "L0 Stall Ref"))
    baseline_color = str(plot_cfg.get("baseline_color", "#E53935"))
    subgroup_band_y0 = float(plot_cfg.get("subgroup_band_y0", 0.885))
    subgroup_band_y1 = float(plot_cfg.get("subgroup_band_y1", 0.935))
    subgroup_band_alpha = float(plot_cfg.get("subgroup_band_alpha", 0.18))
    subgroup_band_colors = plot_cfg.get(
        "subgroup_band_colors",
        ["#D8E7F5", "#FCE8CC", "#DDEEDB", "#F6DDE3"],
    )
    subgroup_label_prefix_group = bool(plot_cfg.get("subgroup_label_prefix_group", False))
    if not isinstance(subgroup_band_colors, list) or not subgroup_band_colors:
        subgroup_band_colors = ["#D8E7F5", "#FCE8CC"]

    xs: List[float] = []
    names: List[str] = []
    group_meta: List[dict] = []
    cur = 0.0
    for g in groups:
        if not isinstance(g, dict):
            continue
        items = [str(c) for c in g.get("counters", [])]
        if not items:
            continue
        group_start_idx = len(names)
        group_start_x = cur
        for c in items:
            xs.append(cur)
            names.append(c)
            cur += 1.0
        group_end_idx = len(names) - 1
        group_end_x = xs[group_end_idx]
        group_meta.append(
            {
                "cfg": g,
                "start_idx": group_start_idx,
                "end_idx": group_end_idx,
                "start_x": group_start_x,
                "end_x": group_end_x,
            }
        )
        cur += float(g.get("gap_after", group_gap))

    if not names:
        raise RuntimeError("analysis.chart_groups_abs is empty after filtering")

    vals = [values.get(n, math.nan) for n in names]
    labels = [short_label(n, aliases) for n in names]
    finite_vals = [v for v in vals if is_finite_number(v)]
    max_val = max(finite_vals) if finite_vals else 1.0
    baseline_val = values.get(baseline_counter, math.nan)
    if is_finite_number(baseline_val):
        max_val = max(max_val, float(baseline_val))
    y_top = max(1.0, max_val * 1.22)
    label_offset = max(1.0, y_top * 0.01)

    fig, ax = plt.subplots(figsize=(max(16, len(names) * 0.55), 6.8))
    ax.bar(xs, vals, width=bar_width, color=bar_color, alpha=bar_alpha)
    ax.set_title(title)
    ax.set_ylabel("Counter Value")
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=75, ha="right", fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    ax.set_ylim(0.0, y_top)

    parent_from_hierarchy = build_hierarchy_parent_map(hierarchy)
    parent_from_group = build_group_ratio_parent_map(groups)

    for x, name, val in zip(xs, names, vals):
        parent = parent_from_hierarchy.get(name, parent_from_group.get(name))
        if parent is None:
            ratio = math.nan
        else:
            ratio = compute_ratio(val, values.get(parent, math.nan))
        bar_top = float(val) if is_finite_number(val) and float(val) > 0 else 0.0
        ax.text(
            x,
            bar_top + label_offset,
            format_ratio(ratio, ratio_decimals),
            ha="center",
            va="bottom",
            fontsize=8,
            color=ratio_color,
        )

    for i in range(len(group_meta) - 1):
        cur_group = group_meta[i]
        next_group = group_meta[i + 1]
        boundary = (cur_group["end_x"] + next_group["start_x"]) / 2.0
        ax.axvline(boundary, color=major_sep_color, linewidth=1.0, alpha=major_sep_alpha)

    for meta in group_meta:
        cfg = meta["cfg"]
        center = (meta["start_x"] + meta["end_x"]) / 2.0
        ax.text(
            center,
            0.965,
            str(cfg.get("name", "")),
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=11,
            color="#444444",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1.2),
        )

        group_counters = [str(c) for c in cfg.get("counters", [])]
        idx_in_group = {name: idx for idx, name in enumerate(group_counters)}
        sub_ranges: List[dict] = []
        for sub in cfg.get("subgroups", []):
            if not isinstance(sub, dict):
                continue
            sub_items = [str(c) for c in sub.get("counters", []) if str(c) in idx_in_group]
            if not sub_items:
                continue
            first = min(idx_in_group[c] for c in sub_items)
            last = max(idx_in_group[c] for c in sub_items)
            start_x = xs[meta["start_idx"] + first]
            end_x = xs[meta["start_idx"] + last]
            sub_ranges.append(
                {
                    "start_x": start_x,
                    "end_x": end_x,
                    "name": str(sub.get("name", "")),
                    "display_name": str(sub.get("display_name", "")),
                }
            )

        group_name = str(cfg.get("name", ""))
        for sub_index, sub in enumerate(sub_ranges):
            sub_center = (sub["start_x"] + sub["end_x"]) / 2.0
            band_color = str(subgroup_band_colors[sub_index % len(subgroup_band_colors)])
            left = sub["start_x"] - bar_width / 2.0
            right = sub["end_x"] + bar_width / 2.0
            band = Rectangle(
                (left, subgroup_band_y0),
                right - left,
                subgroup_band_y1 - subgroup_band_y0,
                transform=ax.get_xaxis_transform(),
                facecolor=band_color,
                edgecolor=subgroup_sep_color,
                linewidth=0.9,
                alpha=subgroup_band_alpha,
                zorder=1,
            )
            ax.add_patch(band)
            base_sub_name = sub.get("display_name") or sub["name"]
            if subgroup_label_prefix_group and group_name:
                sub_display_name = f"{group_name}/{base_sub_name}"
            else:
                sub_display_name = str(base_sub_name)
            span_bars = max(1.0, sub["end_x"] - sub["start_x"] + 1.0)
            sub_fontsize = 8 if span_bars >= 2.0 else 7
            ax.text(
                sub_center,
                (subgroup_band_y0 + subgroup_band_y1) / 2.0,
                sub_display_name,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="center",
                fontsize=sub_fontsize,
                color="#555555",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=0.8),
                clip_on=True,
            )
        for i in range(len(sub_ranges) - 1):
            boundary = (sub_ranges[i]["end_x"] + sub_ranges[i + 1]["start_x"]) / 2.0
            ax.axvline(boundary, color=subgroup_sep_color, linestyle=(0, (4, 2)), linewidth=1.1, alpha=subgroup_sep_alpha)

    if is_finite_number(baseline_val):
        bval = float(baseline_val)
        ax.axhline(bval, color=baseline_color, linestyle="--", linewidth=1.1)
        ax.text(
            xs[-1] + max(0.6, group_gap * 0.45),
            bval,
            f"{baseline_label} = {int(bval) if bval.is_integer() else f'{bval:g}'}",
            color=baseline_color,
            ha="left",
            va="bottom",
            fontsize=9,
        )

    ax.set_xlim(xs[0] - 1.0, xs[-1] + max(1.5, group_gap + 0.6))
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def write_markdown(
    path: Path,
    spec_path: Path,
    log_path: Path,
    values: Mapping[str, float],
    checks: Sequence[dict],
    png: Path,
    csv_path: Path,
    json_path: Path,
    summary_keys: Sequence[str],
):
    ok = sum(1 for c in checks if c.get("passed"))
    total = len(checks)
    lines = [
        "# TMA Report",
        "",
        f"- Spec: `{spec_path}`",
        f"- Log: `{log_path}`",
        f"- Consistency: {ok}/{total} passed",
        f"- Chart: `{png}`",
        f"- CSV: `{csv_path}`",
        f"- Consistency JSON: `{json_path}`",
        "",
        "## Key Values",
        "",
    ]
    for k in summary_keys:
        if k in values:
            lines.append(f"- `{k}` = `{values[k]}`")
    lines += ["", "## Consistency Checks", "", "| Name | Result | Detail |", "|---|---|---|"]
    for c in checks:
        result = "PASS" if c.get("passed") else "FAIL"
        lines.append(f"| {c.get('name')} | {result} | {c.get('detail','')} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rpt(
    path: Path,
    spec_path: Path,
    log_path: Path,
    preset_id: Optional[str],
    run_id: Optional[str],
    sample_time: Optional[int],
    cli_args: Optional[Sequence[str]],
    values: Mapping[str, float],
    direct_names: Sequence[str],
    summary_keys: Sequence[str],
    checks: Sequence[dict],
    hierarchy: Sequence[dict],
    groups: Sequence[dict],
    aliases: Mapping[str, str],
    fallback_used: Mapping[str, str],
    unresolved_missing: Sequence[str],
    baseline_counter: str,
    top_n: int = 10,
):
    lines: List[str] = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    lines.append("# TMA Structured Report (RPT)")
    lines.append("")

    lines.append("[META]")
    lines.append(f"spec={spec_path}")
    lines.append(f"log={log_path}")
    lines.append(f"preset={preset_id if preset_id else 'custom'}")
    lines.append(f"run_id={run_id if run_id else 'N/A'}")
    lines.append(f"sample_time={sample_time if sample_time is not None else 'N/A'}")
    lines.append(f"generated_at_utc={now}")
    if cli_args is not None:
        lines.append(f"arguments={' '.join(str(x) for x in cli_args)}")
    lines.append("")

    lines.append("[KEY_VALUES]")
    for key in summary_keys:
        lines.append(f"{key}={values.get(key, math.nan)}")
    lines.append(f"direct_counter_count={len(direct_names)}")
    lines.append(f"fallback_counter_count={len(fallback_used)}")
    if fallback_used:
        for k, v in fallback_used.items():
            lines.append(f"fallback.{k}={v}")
    lines.append(f"unresolved_missing_count={len(unresolved_missing)}")
    if unresolved_missing:
        lines.append(f"unresolved_missing={','.join(unresolved_missing)}")
    lines.append("")

    lines.append("[CONSISTENCY]")
    lines.append("name|status|severity|detail")
    for c in checks:
        status = "PASS" if c.get("passed") else "FAIL"
        lines.append(f"{c.get('name')}|{status}|{c.get('severity','error')}|{c.get('detail','')}")
    lines.append("")

    lines.append("[TREE_VIEW]")
    lines.append("parent|parent_value|child|child_label|child_value|ratio_to_parent")
    for rel in hierarchy:
        if not isinstance(rel, dict):
            continue
        parent = rel.get("parent")
        if not parent:
            continue
        parent_name = str(parent)
        parent_value = values.get(parent_name, math.nan)
        for child in rel.get("children", []):
            child_name = str(child)
            child_value = values.get(child_name, math.nan)
            ratio = compute_ratio(child_value, parent_value)
            lines.append(
                f"{parent_name}|{parent_value}|{child_name}|{short_label(child_name, aliases)}|{child_value}|{ratio}"
            )
    lines.append("")

    parent_from_hierarchy = build_hierarchy_parent_map(hierarchy)
    lines.append("[CHART_GROUP_VIEW]")
    lines.append("group|counter|label|value|group_parent|ratio_to_group_parent|hierarchy_parent|ratio_to_hierarchy_parent")
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name", ""))
        group_parent = group.get("ratio_parent")
        group_parent_name = str(group_parent) if isinstance(group_parent, str) else ""
        group_parent_value = values.get(group_parent_name, math.nan) if group_parent_name else math.nan
        counters = [str(c) for c in group.get("counters", [])]
        for counter in counters:
            val = values.get(counter, math.nan)
            ratio_group = compute_ratio(val, group_parent_value) if group_parent_name else math.nan
            hier_parent_name = parent_from_hierarchy.get(counter, "")
            hier_parent_value = values.get(hier_parent_name, math.nan) if hier_parent_name else math.nan
            ratio_hier = compute_ratio(val, hier_parent_value) if hier_parent_name else math.nan
            lines.append(
                f"{group_name}|{counter}|{short_label(counter, aliases)}|{val}|{group_parent_name}|{ratio_group}|{hier_parent_name}|{ratio_hier}"
            )
    lines.append("")

    lines.append("[TOP_CONTRIBUTORS]")
    lines.append(f"baseline_counter={baseline_counter}")
    baseline_value = values.get(baseline_counter, math.nan)
    lines.append(f"baseline_value={baseline_value}")
    lines.append("rank|counter|label|value|ratio_to_baseline")
    if is_finite_number(baseline_value) and float(baseline_value) != 0.0:
        seen: Set[str] = set()
        candidates: List[str] = []
        for rel in hierarchy:
            if not isinstance(rel, dict):
                continue
            parent = rel.get("parent")
            if parent:
                p = str(parent)
                if p not in seen:
                    seen.add(p)
                    candidates.append(p)
            for c in rel.get("children", []):
                cn = str(c)
                if cn not in seen:
                    seen.add(cn)
                    candidates.append(cn)
        for g in groups:
            if not isinstance(g, dict):
                continue
            for c in g.get("counters", []):
                cn = str(c)
                if cn not in seen:
                    seen.add(cn)
                    candidates.append(cn)
        ranked: List[Tuple[str, float, float]] = []
        for c in candidates:
            v = values.get(c, math.nan)
            if not is_finite_number(v):
                continue
            ratio = compute_ratio(v, baseline_value)
            ranked.append((c, float(v), ratio))
        ranked.sort(key=lambda x: abs(x[2]) if is_finite_number(x[2]) else -1.0, reverse=True)
        for idx, (counter, v, ratio) in enumerate(ranked[: max(1, int(top_n))], start=1):
            lines.append(f"{idx}|{counter}|{short_label(counter, aliases)}|{v}|{ratio}")
    lines.append("")

    lines.append("[DIAGNOSTIC_NOTES]")
    notes: List[str] = []
    failed = [c for c in checks if not c.get("passed")]
    if failed:
        notes.append(f"failed_consistency_checks={len(failed)}")
        for c in failed:
            notes.append(f"check_fail:{c.get('name')}:{c.get('detail','')}")
    nan_keys = [k for k, v in values.items() if not is_finite_number(v)]
    if nan_keys:
        notes.append(f"nan_or_inf_values={len(nan_keys)}")
        notes.append("nan_or_inf_keys=" + ",".join(nan_keys[:20]))
    for rel in hierarchy:
        if not isinstance(rel, dict):
            continue
        parent = rel.get("parent")
        if not parent:
            continue
        p = str(parent)
        pv = values.get(p, math.nan)
        for child in rel.get("children", []):
            c = str(child)
            cv = values.get(c, math.nan)
            r = compute_ratio(cv, pv)
            if is_finite_number(r) and abs(float(r)) > 1.0:
                notes.append(f"ratio_gt_1:{c}/parent={p}:ratio={r}")
    if not notes:
        notes.append("none")
    for n in notes:
        lines.append(f"- {n}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _sanitize_part(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip())
    return s.strip("-") or "unnamed"


def _default_run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _prefix_output_paths(out_prefix: Path) -> Tuple[Path, Path, Path, Path, Path]:
    csv_path = out_prefix.with_name(out_prefix.name + "_values.csv")
    png_path = out_prefix.with_name(out_prefix.name + "_combined.png")
    md_path = out_prefix.with_name(out_prefix.name + "_report.md")
    json_path = out_prefix.with_name(out_prefix.name + "_consistency.json")
    rpt_path = out_prefix.with_name(out_prefix.name + "_report.rpt")
    return csv_path, png_path, md_path, json_path, rpt_path


def _archive_output_paths(out_root: Path, preset_id: str, run_id: str) -> Tuple[Path, Path, Path, Path, Path, Path]:
    parts = [_sanitize_part(p) for p in preset_id.split("/") if p.strip()]
    if not parts:
        parts = ["custom", "default"]
    run_dir = out_root.joinpath(*parts, _sanitize_part(run_id))
    csv_path = run_dir / "values.csv"
    png_path = run_dir / "combined.png"
    md_path = run_dir / "report.md"
    json_path = run_dir / "consistency.json"
    rpt_path = run_dir / "report.rpt"
    return run_dir, csv_path, png_path, md_path, json_path, rpt_path


def run_report(
    spec_path: Path,
    log_path: Path,
    out_prefix: Optional[Path],
    strict: bool,
    out_root: Optional[Path] = None,
    run_id: Optional[str] = None,
    backup_log: bool = True,
    preset_id: Optional[str] = None,
    cli_args: Optional[Sequence[str]] = None,
) -> int:
    resolved_spec_path = spec_path.resolve()
    spec = load_spec(resolved_spec_path)
    ana = resolve_analysis(spec)

    parse_cfg = ana.get("parse", {})
    direct_names = collect_direct_names(spec, ana)
    direct_set = set(direct_names)

    parsed = parse_log(log_path, parse_cfg, direct_set)
    missing = [n for n in direct_names if n not in parsed.counters]

    formulas = ana.get("derived_counters", {})
    derived = derive(direct_names, parsed.counters, formulas)

    all_values: Dict[str, float] = {n: parsed.counters.get(n, math.nan) for n in direct_names}
    all_values.update(derived)

    fallback_cfg = ana.get("missing_direct_fallback", {})
    if not isinstance(fallback_cfg, dict):
        fallback_cfg = {}
    fallback_used = apply_missing_direct_fallback(all_values, missing, fallback_cfg)
    unresolved_missing = [n for n in missing if not is_finite_number(all_values.get(n, math.nan))]
    if unresolved_missing:
        msg = f"missing direct counters ({len(unresolved_missing)}): {', '.join(unresolved_missing)}"
        if strict:
            raise RuntimeError(msg)
        print(f"[WARN] {msg}", file=sys.stderr)
    if fallback_used:
        used_desc = ", ".join(f"{k}<-{v}" for k, v in fallback_used.items())
        print(f"[INFO] applied fallback for missing direct counters: {used_desc}")

    checks_cfg = ana.get("consistency_checks", [])
    checks = compute_checks(all_values, checks_cfg)

    run_dir: Optional[Path] = None
    log_backup_path: Optional[Path] = None
    meta_path: Optional[Path] = None
    rpt_path: Optional[Path] = None
    effective_run_id: Optional[str] = run_id
    if out_prefix is not None:
        out_prefix.parent.mkdir(parents=True, exist_ok=True)
        csv_path, png_path, md_path, json_path, rpt_path = _prefix_output_paths(out_prefix)
    else:
        if out_root is None:
            raise ValueError("out_root is required when out_prefix is not provided")
        effective_preset = preset_id or f"custom/{resolved_spec_path.stem}"
        effective_run_id = run_id or _default_run_id()
        run_dir, csv_path, png_path, md_path, json_path, rpt_path = _archive_output_paths(out_root, effective_preset, effective_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = run_dir / "run_meta.json"
        if backup_log:
            log_backup_path = run_dir / "input.log"
            shutil.copy2(log_path, log_backup_path)

    groups = ana.get("chart_groups_abs", [])
    hierarchy = ana.get("hierarchy", [])
    ratios = collect_ratio_rows(all_values, hierarchy, groups)

    write_csv(csv_path, direct_names, parsed.counters, derived, formulas, ratios, all_values, fallback_used)
    plot(
        all_values,
        groups,
        ana.get("display_aliases", {}),
        hierarchy,
        ana.get("plot", {}),
        png_path,
    )

    json_path.write_text(json.dumps({"checks": checks}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_keys_cfg = ana.get("summary_keys", [])
    summary_keys = [str(k) for k in summary_keys_cfg] if isinstance(summary_keys_cfg, list) else []
    write_markdown(md_path, resolved_spec_path, log_path, all_values, checks, png_path, csv_path, json_path, summary_keys)
    plot_cfg = ana.get("plot", {})
    baseline_counter = str(plot_cfg.get("baseline_counter", "CUTE_L0_TC_Stall")) if isinstance(plot_cfg, dict) else "CUTE_L0_TC_Stall"
    write_rpt(
        path=rpt_path if rpt_path is not None else md_path.with_suffix(".rpt"),
        spec_path=resolved_spec_path,
        log_path=log_path,
        preset_id=preset_id,
        run_id=effective_run_id,
        sample_time=parsed.last_time,
        cli_args=cli_args,
        values=all_values,
        direct_names=direct_names,
        summary_keys=summary_keys,
        checks=checks,
        hierarchy=hierarchy,
        groups=groups,
        aliases=ana.get("display_aliases", {}),
        fallback_used=fallback_used,
        unresolved_missing=unresolved_missing,
        baseline_counter=baseline_counter,
    )

    if meta_path is not None:
        meta = {
            "preset": preset_id,
            "resolved_spec": str(resolved_spec_path),
            "spec_input": str(spec_path),
            "log_input": str(log_path),
            "log_backup": str(log_backup_path) if log_backup_path else None,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "run_id": effective_run_id,
            "arguments": list(cli_args) if cli_args is not None else None,
            "fallback_used": fallback_used,
            "sample_time": parsed.last_time,
            "outputs": {
                "csv": str(csv_path),
                "png": str(png_path),
                "markdown": str(md_path),
                "consistency": str(json_path),
                "rpt": str(rpt_path) if rpt_path is not None else None,
            },
        }
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[INFO] sample_time={parsed.last_time if parsed.last_time is not None else 'N/A'}")
    print(f"[INFO] resolved_spec={resolved_spec_path}")
    print(f"[INFO] values_csv={csv_path}")
    print(f"[INFO] chart={png_path}")
    print(f"[INFO] report={md_path}")
    print(f"[INFO] consistency={json_path}")
    if rpt_path is not None:
        print(f"[INFO] rpt={rpt_path}")
    if log_backup_path is not None:
        print(f"[INFO] log_backup={log_backup_path}")
    if meta_path is not None:
        print(f"[INFO] run_meta={meta_path}")

    failed_errors = [c for c in checks if (not c.get("passed")) and c.get("severity", "error") == "error"]
    return 1 if failed_errors else 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate TMA report from log + preset")
    p.add_argument("--preset-file", type=Path, required=True)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--out-prefix", type=Path, default=None)
    p.add_argument("--out-root", type=Path, default=Path(__file__).resolve().parent / "reports")
    p.add_argument("--run-id", type=str, default=None)
    p.add_argument("--backup-log", dest="backup_log", action="store_true", default=True)
    p.add_argument("--no-backup-log", dest="backup_log", action="store_false")
    p.add_argument("--preset-id", type=str, default=None)
    p.add_argument("--strict", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    if plt is None:
        print("[ERROR] matplotlib is not installed. Please install it first:", file=sys.stderr)
        print("        python3 -m pip install matplotlib", file=sys.stderr)
        return 2
    return run_report(
        spec_path=args.preset_file.resolve(),
        log_path=args.log.resolve(),
        out_prefix=args.out_prefix.resolve() if args.out_prefix else None,
        strict=args.strict,
        out_root=args.out_root.resolve() if args.out_root else None,
        run_id=args.run_id,
        backup_log=args.backup_log,
        preset_id=args.preset_id,
        cli_args=list(argv) if argv is not None else list(sys.argv[1:]),
    )


if __name__ == "__main__":
    raise SystemExit(main())
