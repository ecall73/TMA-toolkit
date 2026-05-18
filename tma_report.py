#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import datetime as dt
import html
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

import yaml

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:  # pragma: no cover
    go = None


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


def short_label(name: str, aliases: Mapping[str, str]) -> str:
    if name in aliases:
        return aliases[name]
    return name


def format_value(v: float) -> str:
    if not is_finite_number(v):
        return "NaN"
    fv = float(v)
    if fv.is_integer():
        return str(int(fv))
    return f"{fv:.6g}"


def format_ratio(v: float, decimals: int = 4) -> str:
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


def collect_tree_rows(values: Mapping[str, float], hierarchy: Sequence[dict], aliases: Mapping[str, str]) -> List[dict]:
    rows: List[dict] = []
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
            rows.append(
                {
                    "parent": parent_name,
                    "parent_value": parent_value,
                    "child": child_name,
                    "child_label": short_label(child_name, aliases),
                    "child_value": child_value,
                    "ratio_to_parent": ratio,
                }
            )
    return rows


def collect_group_rows(values: Mapping[str, float], groups: Sequence[dict], aliases: Mapping[str, str], hierarchy: Sequence[dict]) -> List[dict]:
    rows: List[dict] = []
    parent_from_hierarchy = build_hierarchy_parent_map(hierarchy)
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
            rows.append(
                {
                    "group": group_name,
                    "counter": counter,
                    "label": short_label(counter, aliases),
                    "value": val,
                    "group_parent": group_parent_name,
                    "ratio_to_group_parent": ratio_group,
                    "hierarchy_parent": hier_parent_name,
                    "ratio_to_hierarchy_parent": ratio_hier,
                }
            )
    return rows


def collect_top_contributors(
    values: Mapping[str, float],
    hierarchy: Sequence[dict],
    groups: Sequence[dict],
    aliases: Mapping[str, str],
    baseline_counter: str,
    top_n: int = 10,
) -> Tuple[float, List[dict]]:
    baseline_value = values.get(baseline_counter, math.nan)
    if not is_finite_number(baseline_value) or float(baseline_value) == 0.0:
        return baseline_value, []

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
    rows: List[dict] = []
    for idx, (counter, v, ratio) in enumerate(ranked[: max(1, int(top_n))], start=1):
        rows.append(
            {
                "rank": idx,
                "counter": counter,
                "label": short_label(counter, aliases),
                "value": v,
                "ratio_to_baseline": ratio,
            }
        )

    return float(baseline_value), rows


def collect_diagnostic_notes(values: Mapping[str, float], checks: Sequence[dict], hierarchy: Sequence[dict]) -> List[str]:
    notes: List[str] = []

    failed = [c for c in checks if not c.get("passed")]
    if failed:
        notes.append(f"failed_consistency_checks={len(failed)}")
        for c in failed:
            notes.append(f"check_fail:{c.get('name')}:{c.get('detail', '')}")

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

    return notes


def _fallback_groups(values: Mapping[str, float], summary_keys: Sequence[str], baseline_counter: str) -> List[dict]:
    counters: List[str] = []
    seen: Set[str] = set()
    for key in summary_keys:
        k = str(key)
        if k == baseline_counter:
            continue
        if k in seen:
            continue
        v = values.get(k, math.nan)
        if is_finite_number(v):
            seen.add(k)
            counters.append(k)
    if not counters:
        return []
    return [{"name": "Summary", "ratio_parent": baseline_counter, "counters": counters[:12]}]


def build_group_breakdown_chart_html(
    values: Mapping[str, float],
    groups: Sequence[dict],
    aliases: Mapping[str, str],
    hierarchy: Sequence[dict],
    baseline_counter: str,
    summary_keys: Sequence[str],
) -> str:
    if go is None:
        return "<div class='empty'>Plotly not available.</div>"

    use_groups = [g for g in groups if isinstance(g, dict) and g.get("counters")]
    if not use_groups:
        use_groups = _fallback_groups(values, summary_keys, baseline_counter)
    if not use_groups:
        return "<div class='empty'>No chart_groups_abs and no summary fallback counters available.</div>"

    parent_from_hierarchy = build_hierarchy_parent_map(hierarchy)
    parent_from_group = build_group_ratio_parent_map(use_groups)

    x_labels: List[str] = []
    y_values: List[float] = []
    ratio_text: List[str] = []
    hover_text: List[str] = []
    group_names: List[str] = []

    for g in use_groups:
        gname = str(g.get("name", ""))
        for c in [str(x) for x in g.get("counters", [])]:
            val = values.get(c, math.nan)
            y = float(val) if is_finite_number(val) else 0.0
            parent = parent_from_hierarchy.get(c, parent_from_group.get(c, ""))
            ratio = compute_ratio(val, values.get(parent, math.nan)) if parent else math.nan
            label = short_label(c, aliases)
            x_labels.append(f"{gname}/{label}" if gname else label)
            y_values.append(y)
            ratio_text.append(format_ratio(ratio, 4))
            hover_text.append(
                "<br>".join(
                    [
                        f"group={html.escape(gname)}",
                        f"counter={html.escape(c)}",
                        f"label={html.escape(label)}",
                        f"value={format_value(val)}",
                        f"parent={html.escape(parent) if parent else 'N/A'}",
                        f"ratio={format_ratio(ratio, 6)}",
                    ]
                )
            )
            group_names.append(gname)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=y_values,
            text=ratio_text,
            textposition="outside",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover_text,
            marker=dict(color="#4C78A8"),
            name="Group Breakdown",
        )
    )

    for i in range(1, len(group_names)):
        if group_names[i] != group_names[i - 1]:
            fig.add_vline(x=i - 0.5, line_width=1, line_dash="dot", line_color="#A0A0A0")

    baseline_value = values.get(baseline_counter, math.nan)
    if is_finite_number(baseline_value):
        fig.add_hline(
            y=float(baseline_value),
            line_dash="dash",
            line_color="#E53935",
            annotation_text=f"{baseline_counter}={format_value(baseline_value)}",
            annotation_position="top right",
        )

    fig.update_layout(
        title="Chart Groups Breakdown",
        xaxis_title="Group/Counter",
        yaxis_title="Value",
        hovermode="closest",
        dragmode="pan",
        margin=dict(l=50, r=30, t=60, b=140),
        height=560,
    )
    fig.update_xaxes(tickangle=65)

    return fig.to_html(include_plotlyjs="cdn", full_html=False, div_id="chart_groups_fig")


def build_top_contributors_chart_html(top_rows: Sequence[dict], baseline_counter: str, baseline_value: float) -> str:
    if go is None:
        return "<div class='empty'>Plotly not available.</div>"
    if not top_rows:
        return "<div class='empty'>No finite contributors for top list.</div>"

    labels = [f"#{r['rank']} {r['label']}" for r in top_rows]
    ratios = [float(r["ratio_to_baseline"]) if is_finite_number(r["ratio_to_baseline"]) else 0.0 for r in top_rows]
    values = [float(r["value"]) if is_finite_number(r["value"]) else 0.0 for r in top_rows]
    hover = [
        "<br>".join(
            [
                f"counter={html.escape(str(r['counter']))}",
                f"label={html.escape(str(r['label']))}",
                f"value={format_value(r['value'])}",
                f"ratio_to_{baseline_counter}={format_ratio(r['ratio_to_baseline'], 6)}",
            ]
        )
        for r in top_rows
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=labels,
            x=ratios,
            orientation="h",
            text=[format_ratio(x, 4) for x in ratios],
            textposition="outside",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover,
            marker=dict(color="#F57C00"),
            name="Ratio to Baseline",
        )
    )

    fig.update_layout(
        title=f"Top Contributors (baseline: {baseline_counter}={format_value(baseline_value)})",
        xaxis_title="Ratio to Baseline",
        yaxis_title="Counter",
        hovermode="closest",
        margin=dict(l=180, r=30, t=60, b=60),
        height=max(420, 60 + 42 * len(labels)),
    )

    return fig.to_html(include_plotlyjs=False, full_html=False, div_id="top_contributors_fig")


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[str]], klass: str = "") -> str:
    cls = f" class='{klass}'" if klass else ""
    h = [f"<table{cls}><thead><tr>"]
    for header in headers:
        h.append(f"<th>{html.escape(str(header))}</th>")
    h.append("</tr></thead><tbody>")
    for row in rows:
        h.append("<tr>")
        for cell in row:
            h.append(f"<td>{cell}</td>")
        h.append("</tr>")
    h.append("</tbody></table>")
    return "".join(h)


def render_html_report(
    path: Path,
    spec_path: Path,
    log_path: Path,
    preset_id: Optional[str],
    sample_time: Optional[int],
    direct_names: Sequence[str],
    formulas: Mapping[str, str],
    values: Mapping[str, float],
    checks: Sequence[dict],
    unresolved_missing: Sequence[str],
    tree_rows: Sequence[dict],
    group_rows: Sequence[dict],
    ratio_rows: Sequence[Tuple[str, str, float]],
    top_rows: Sequence[dict],
    diagnostic_notes: Sequence[str],
    chart_groups_html: str,
    top_contributors_html: str,
    summary_keys: Sequence[str],
):
    ok = sum(1 for c in checks if c.get("passed"))
    total = len(checks)

    direct_rows = []
    for name in direct_names:
        direct_rows.append((name, format_value(values.get(name, math.nan))))

    derived_rows = []
    for name, expr in formulas.items():
        derived_rows.append((name, html.escape(expr), format_value(values.get(name, math.nan))))

    summary_rows = []
    for key in summary_keys:
        k = str(key)
        summary_rows.append((k, format_value(values.get(k, math.nan))))

    tree_table_rows = []
    for r in tree_rows:
        tree_table_rows.append(
            (
                html.escape(str(r["parent"])),
                format_value(r["parent_value"]),
                html.escape(str(r["child"])),
                html.escape(str(r["child_label"])),
                format_value(r["child_value"]),
                format_ratio(r["ratio_to_parent"], 6),
            )
        )

    group_table_rows = []
    for r in group_rows:
        group_table_rows.append(
            (
                html.escape(str(r["group"])),
                html.escape(str(r["counter"])),
                html.escape(str(r["label"])),
                format_value(r["value"]),
                html.escape(str(r["group_parent"])),
                format_ratio(r["ratio_to_group_parent"], 6),
                html.escape(str(r["hierarchy_parent"])),
                format_ratio(r["ratio_to_hierarchy_parent"], 6),
            )
        )

    ratio_table_rows = []
    for counter, parent, ratio in ratio_rows:
        ratio_table_rows.append(
            (
                html.escape(counter),
                html.escape(parent),
                format_value(values.get(counter, math.nan)),
                format_ratio(ratio, 6),
            )
        )

    check_rows = []
    for c in checks:
        status = "PASS" if c.get("passed") else "FAIL"
        cls = "pass" if c.get("passed") else "fail"
        check_rows.append(
            (
                html.escape(str(c.get("name"))),
                f"<span class='{cls}'>{status}</span>",
                html.escape(str(c.get("severity", "error"))),
                html.escape(str(c.get("detail", ""))),
            )
        )

    top_table_rows = []
    for r in top_rows:
        top_table_rows.append(
            (
                str(r["rank"]),
                html.escape(str(r["counter"])),
                html.escape(str(r["label"])),
                format_value(r["value"]),
                format_ratio(r["ratio_to_baseline"], 6),
            )
        )

    missing_html = ""
    if unresolved_missing:
        missing_html = "<div class='warn'><strong>Unresolved Missing Direct Counters:</strong> " + ", ".join(
            html.escape(x) for x in unresolved_missing
        ) + "</div>"

    notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in diagnostic_notes)

    meta_pairs = [
        ("Spec", str(spec_path)),
        ("Log", str(log_path)),
        ("Preset", preset_id if preset_id else "custom"),
        ("Sample Time", str(sample_time) if sample_time is not None else "N/A"),
        ("Direct Counters", str(len(direct_names))),
        ("Derived Counters", str(len(formulas))),
        ("Consistency", f"{ok}/{total} passed"),
    ]
    meta_html = "".join(
        f"<div class='meta-item'><div class='meta-k'>{html.escape(k)}</div><div class='meta-v'>{html.escape(v)}</div></div>"
        for k, v in meta_pairs
    )

    summary_table = _html_table(["Metric", "Value"], summary_rows, klass="dense")
    direct_table = _html_table(["Counter", "Value"], direct_rows, klass="dense")
    derived_table = _html_table(["Counter", "Formula", "Value"], derived_rows, klass="dense")
    tree_table = _html_table(
        ["Parent", "Parent Value", "Child", "Child Label", "Child Value", "Ratio To Parent"],
        tree_table_rows,
        klass="dense",
    )
    group_table = _html_table(
        [
            "Group",
            "Counter",
            "Label",
            "Value",
            "Group Parent",
            "Ratio To Group Parent",
            "Hierarchy Parent",
            "Ratio To Hierarchy Parent",
        ],
        group_table_rows,
        klass="dense",
    )
    ratio_table = _html_table(["Counter", "Parent", "Value", "Ratio In Parent"], ratio_table_rows, klass="dense")
    checks_table = _html_table(["Name", "Status", "Severity", "Detail"], check_rows, klass="dense")
    top_table = _html_table(["Rank", "Counter", "Label", "Value", "Ratio To Baseline"], top_table_rows, klass="dense")

    html_content = f"""
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>TMA Toolkit Report</title>
  <script>
    function switchView(viewId, tabElement) {{
      const targetView = document.getElementById(viewId);
      if (!targetView) return;
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      targetView.classList.add('active');
      tabElement.classList.add('active');
      setTimeout(() => {{
        const plotlyDivs = targetView.querySelectorAll('.plotly-graph-div');
        plotlyDivs.forEach(div => {{
          if (window.Plotly && div.layout) {{
            window.Plotly.Plots.resize(div);
          }}
        }});
      }}, 100);
    }}
  </script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; margin: 0; background: #f5f6f8; color: #222; }}
    .header {{ background: #EB5127; color: white; padding: 18px 22px; }}
    .header h1 {{ margin: 0; font-size: 24px; }}
    .header p {{ margin: 6px 0 0 0; font-size: 13px; opacity: 0.95; }}
    .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 14px; }}
    .meta-item {{ background: rgba(255,255,255,0.14); padding: 10px 12px; border-radius: 8px; }}
    .meta-k {{ font-size: 12px; opacity: 0.9; }}
    .meta-v {{ margin-top: 4px; font-size: 14px; font-weight: 600; word-break: break-all; }}
    .tab-container {{ background: #fff; border-bottom: 1px solid #ddd; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .tabs {{ display: flex; gap: 0; padding: 0 16px; }}
    .tab {{ border: none; background: none; cursor: pointer; padding: 14px 20px; font-size: 15px; color: #666; border-bottom: 3px solid transparent; }}
    .tab:hover {{ background: #f7f7f7; color: #EB5127; }}
    .tab.active {{ color: #EB5127; border-bottom-color: #EB5127; font-weight: 600; }}
    .content {{ padding: 16px; }}
    .view {{ display: none; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 16px; }}
    .view.active {{ display: block; }}
    .section {{ margin: 0 0 18px 0; }}
    .section h3 {{ margin: 0 0 8px 0; font-size: 17px; color: #EB5127; }}
    .section p {{ margin: 0 0 8px 0; color: #555; line-height: 1.5; }}
    .card {{ border: 1px solid #e6e8ec; border-radius: 8px; padding: 12px; background: #fafbfc; }}
    .split {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
    @media (min-width: 1200px) {{ .split {{ grid-template-columns: 1fr 1fr; }} }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #e1e4e8; padding: 6px 8px; text-align: left; vertical-align: top; font-size: 12px; }}
    th {{ background: #f3f5f7; position: sticky; top: 0; z-index: 1; }}
    .dense-wrap {{ max-height: 360px; overflow: auto; border: 1px solid #e1e4e8; border-radius: 6px; }}
    .dense th, .dense td {{ font-size: 11px; padding: 5px 7px; }}
    .pass {{ color: #1b873f; font-weight: 700; }}
    .fail {{ color: #c62828; font-weight: 700; }}
    .warn {{ margin: 10px 0; padding: 10px; background: #fff4e5; border-left: 4px solid #f57c00; border-radius: 4px; font-size: 13px; }}
    .empty {{ color: #666; background: #f7f7f7; padding: 12px; border-radius: 6px; border: 1px dashed #cfcfcf; }}
    ul.notes {{ margin: 8px 0 0 20px; }}
    ul.notes li {{ margin: 4px 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <div class=\"header\">
    <h1>TMA Toolkit HTML Report</h1>
    <p>Preset-driven analysis report (HTML + RPT + consistency.json)</p>
    <div class=\"meta-grid\">{meta_html}</div>
  </div>

  <div class=\"tab-container\">
    <div class=\"tabs\">
      <button class=\"tab active\" onclick=\"switchView('view0', this)\">Overview</button>
      <button class=\"tab\" onclick=\"switchView('view1', this)\">Breakdown</button>
      <button class=\"tab\" onclick=\"switchView('view2', this)\">Charts</button>
      <button class=\"tab\" onclick=\"switchView('view3', this)\">Consistency</button>
    </div>
  </div>

  <div class=\"content\">
    <div id=\"view0\" class=\"view active\">
      <div class=\"section\">
        <h3>Key Metrics</h3>
        <div class=\"dense-wrap\">{summary_table}</div>
      </div>
      <div class=\"split\">
        <div class=\"section card\">
          <h3>Direct Counters</h3>
          <div class=\"dense-wrap\">{direct_table}</div>
        </div>
        <div class=\"section card\">
          <h3>Derived Counters</h3>
          <div class=\"dense-wrap\">{derived_table}</div>
        </div>
      </div>
      {missing_html}
    </div>

    <div id=\"view1\" class=\"view\">
      <div class=\"section\">
        <h3>Hierarchy Tree View</h3>
        <div class=\"dense-wrap\">{tree_table}</div>
      </div>
      <div class=\"section\">
        <h3>Chart Group View</h3>
        <div class=\"dense-wrap\">{group_table}</div>
      </div>
      <div class=\"section\">
        <h3>Ratio Rows</h3>
        <div class=\"dense-wrap\">{ratio_table}</div>
      </div>
    </div>

    <div id=\"view2\" class=\"view\">
      <div class=\"section\">
        <h3>Chart Groups Breakdown</h3>
        {chart_groups_html}
      </div>
      <div class=\"section\">
        <h3>Top Contributors</h3>
        {top_contributors_html}
      </div>
      <div class=\"section\">
        <h3>Top Contributors Table</h3>
        <div class=\"dense-wrap\">{top_table}</div>
      </div>
    </div>

    <div id=\"view3\" class=\"view\">
      <div class=\"section\">
        <h3>Consistency Checks</h3>
        <div class=\"dense-wrap\">{checks_table}</div>
      </div>
      <div class=\"section\">
        <h3>Diagnostic Notes</h3>
        <ul class=\"notes\">{notes_html}</ul>
      </div>
    </div>
  </div>
</body>
</html>
"""

    path.write_text(html_content, encoding="utf-8")


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
        lines.append(f"{c.get('name')}|{status}|{c.get('severity', 'error')}|{c.get('detail', '')}")
    lines.append("")

    lines.append("[TREE_VIEW]")
    lines.append("parent|parent_value|child|child_label|child_value|ratio_to_parent")
    for r in collect_tree_rows(values, hierarchy, aliases):
        lines.append(
            f"{r['parent']}|{r['parent_value']}|{r['child']}|{r['child_label']}|{r['child_value']}|{r['ratio_to_parent']}"
        )
    lines.append("")

    lines.append("[CHART_GROUP_VIEW]")
    lines.append("group|counter|label|value|group_parent|ratio_to_group_parent|hierarchy_parent|ratio_to_hierarchy_parent")
    for r in collect_group_rows(values, groups, aliases, hierarchy):
        lines.append(
            f"{r['group']}|{r['counter']}|{r['label']}|{r['value']}|{r['group_parent']}|{r['ratio_to_group_parent']}|{r['hierarchy_parent']}|{r['ratio_to_hierarchy_parent']}"
        )
    lines.append("")

    lines.append("[TOP_CONTRIBUTORS]")
    lines.append(f"baseline_counter={baseline_counter}")
    baseline_value, top_rows = collect_top_contributors(values, hierarchy, groups, aliases, baseline_counter, top_n)
    lines.append(f"baseline_value={baseline_value}")
    lines.append("rank|counter|label|value|ratio_to_baseline")
    for r in top_rows:
        lines.append(f"{r['rank']}|{r['counter']}|{r['label']}|{r['value']}|{r['ratio_to_baseline']}")
    lines.append("")

    lines.append("[DIAGNOSTIC_NOTES]")
    for note in collect_diagnostic_notes(values, checks, hierarchy):
        lines.append(f"- {note}")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _sanitize_part(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip())
    return s.strip("-") or "unnamed"


def _default_run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _prefix_output_paths(out_prefix: Path) -> Tuple[Path, Path, Path]:
    html_path = out_prefix.with_name(out_prefix.name + "_report.html")
    json_path = out_prefix.with_name(out_prefix.name + "_consistency.json")
    rpt_path = out_prefix.with_name(out_prefix.name + "_report.rpt")
    return html_path, json_path, rpt_path


def _archive_output_paths(out_root: Path, preset_id: str, run_id: str) -> Tuple[Path, Path, Path, Path]:
    parts = [_sanitize_part(p) for p in preset_id.split("/") if p.strip()]
    if not parts:
        parts = ["custom", "default"]
    run_dir = out_root.joinpath(*parts, _sanitize_part(run_id))
    html_path = run_dir / "report.html"
    json_path = run_dir / "consistency.json"
    rpt_path = run_dir / "report.rpt"
    return run_dir, html_path, json_path, rpt_path


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
    # backup_log is preserved for CLI compatibility, but report outputs no longer back up input logs.
    _ = backup_log

    resolved_spec_path = spec_path.resolve()
    spec = load_spec(resolved_spec_path)
    ana = resolve_analysis(spec)

    parse_cfg = ana.get("parse", {})
    direct_names = collect_direct_names(spec, ana)
    direct_set = set(direct_names)

    parsed = parse_log(log_path, parse_cfg, direct_set)
    missing = [n for n in direct_names if n not in parsed.counters]

    formulas = ana.get("derived_counters", {})
    if not isinstance(formulas, dict):
        formulas = {}
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

    checks_cfg = ana.get("consistency_checks", [])
    if not isinstance(checks_cfg, list):
        checks_cfg = []
    checks = compute_checks(all_values, checks_cfg)

    if out_prefix is not None:
        out_prefix.parent.mkdir(parents=True, exist_ok=True)
        html_path, json_path, rpt_path = _prefix_output_paths(out_prefix)
    else:
        if out_root is None:
            raise ValueError("out_root is required when out_prefix is not provided")
        effective_preset = preset_id or f"custom/{resolved_spec_path.stem}"
        effective_run_id = run_id or _default_run_id()
        run_dir, html_path, json_path, rpt_path = _archive_output_paths(out_root, effective_preset, effective_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

    groups = ana.get("chart_groups_abs", [])
    if not isinstance(groups, list):
        groups = []
    hierarchy = ana.get("hierarchy", [])
    if not isinstance(hierarchy, list):
        hierarchy = []
    aliases = ana.get("display_aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}

    summary_keys_cfg = ana.get("summary_keys", [])
    summary_keys = [str(k) for k in summary_keys_cfg] if isinstance(summary_keys_cfg, list) else []

    plot_cfg = ana.get("plot", {})
    baseline_counter = str(plot_cfg.get("baseline_counter", "CUTE_L0_TC_Stall")) if isinstance(plot_cfg, dict) else "CUTE_L0_TC_Stall"

    ratio_rows = collect_ratio_rows(all_values, hierarchy, groups)
    tree_rows = collect_tree_rows(all_values, hierarchy, aliases)
    group_rows = collect_group_rows(all_values, groups, aliases, hierarchy)
    baseline_value, top_rows = collect_top_contributors(all_values, hierarchy, groups, aliases, baseline_counter, top_n=10)
    diagnostic_notes = collect_diagnostic_notes(all_values, checks, hierarchy)

    chart_groups_html = build_group_breakdown_chart_html(
        values=all_values,
        groups=groups,
        aliases=aliases,
        hierarchy=hierarchy,
        baseline_counter=baseline_counter,
        summary_keys=summary_keys,
    )
    top_contributors_html = build_top_contributors_chart_html(top_rows, baseline_counter, baseline_value)

    render_html_report(
        path=html_path,
        spec_path=resolved_spec_path,
        log_path=log_path,
        preset_id=preset_id,
        sample_time=parsed.last_time,
        direct_names=direct_names,
        formulas=formulas,
        values=all_values,
        checks=checks,
        unresolved_missing=unresolved_missing,
        tree_rows=tree_rows,
        group_rows=group_rows,
        ratio_rows=ratio_rows,
        top_rows=top_rows,
        diagnostic_notes=diagnostic_notes,
        chart_groups_html=chart_groups_html,
        top_contributors_html=top_contributors_html,
        summary_keys=summary_keys,
    )

    json_path.write_text(json.dumps({"checks": checks}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    write_rpt(
        path=rpt_path,
        spec_path=resolved_spec_path,
        log_path=log_path,
        preset_id=preset_id,
        run_id=run_id,
        sample_time=parsed.last_time,
        cli_args=list(cli_args) if cli_args is not None else list(sys.argv[1:]),
        values=all_values,
        direct_names=direct_names,
        summary_keys=summary_keys,
        checks=checks,
        hierarchy=hierarchy,
        groups=groups,
        aliases=aliases,
        fallback_used=fallback_used,
        unresolved_missing=unresolved_missing,
        baseline_counter=baseline_counter,
    )

    print(f"[INFO] sample_time={parsed.last_time if parsed.last_time is not None else 'N/A'}")
    print(f"[INFO] resolved_spec={resolved_spec_path}")
    print(f"[INFO] html={html_path}")
    print(f"[INFO] consistency={json_path}")
    print(f"[INFO] rpt={rpt_path}")

    failed_errors = [c for c in checks if (not c.get("passed")) and c.get("severity", "error") == "error"]
    return 1 if failed_errors else 0


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate TMA HTML report from log + preset")
    p.add_argument("--preset-file", type=Path, required=True)
    p.add_argument("--log", type=Path, required=True)
    p.add_argument("--out-prefix", type=Path, default=None)
    p.add_argument("--out-root", type=Path, default=Path(__file__).resolve().parent / "reports")
    p.add_argument("--run-id", type=str, default=None)
    p.add_argument(
        "--backup-log",
        dest="backup_log",
        action="store_true",
        default=True,
        help="Compatibility flag (no-op in HTML/RPT/JSON flow)",
    )
    p.add_argument(
        "--no-backup-log",
        dest="backup_log",
        action="store_false",
        help="Compatibility flag (no-op in HTML/RPT/JSON flow)",
    )
    p.add_argument("--preset-id", type=str, default=None)
    p.add_argument("--strict", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    if go is None:
        print("[ERROR] plotly is not installed. Please install it first:", file=sys.stderr)
        print("        uv sync --project tools/TMA-toolkit", file=sys.stderr)
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
