"""Renderers for diff results: human text, JSON (for tooling), Markdown (for PRs)."""
from __future__ import annotations

import json

from .diff import BREAKING, INFO, NON_BREAKING, Change


def summarize(changes: list[Change]) -> dict:
    counts = {BREAKING: 0, NON_BREAKING: 0, INFO: 0}
    for c in changes:
        counts[c.severity] += 1
    return counts


def render_text(changes: list[Change]) -> str:
    counts = summarize(changes)
    lines = [
        f"specguard: {counts[BREAKING]} breaking, "
        f"{counts[NON_BREAKING]} non-breaking, {counts[INFO]} informational"
    ]
    if not changes:
        lines.append("No changes detected.")
        return "\n".join(lines)
    for severity, label in ((BREAKING, "BREAKING"), (NON_BREAKING, "NON-BREAKING"), (INFO, "INFO")):
        group = [c for c in changes if c.severity == severity]
        if not group:
            continue
        lines.append("")
        lines.append(f"== {label} ({len(group)}) ==")
        for c in group:
            lines.append(f"  [{c.category}] {c.location}\n      {c.message}")
    return "\n".join(lines)


def render_json(changes: list[Change]) -> str:
    return json.dumps(
        {"summary": summarize(changes), "changes": [c.to_dict() for c in changes]},
        indent=2,
    )


def render_markdown(changes: list[Change]) -> str:
    counts = summarize(changes)
    lines = [
        "# API Change Report",
        "",
        f"**{counts[BREAKING]}** breaking · **{counts[NON_BREAKING]}** non-breaking · "
        f"**{counts[INFO]}** informational",
        "",
    ]
    if not changes:
        lines.append("No changes detected.")
    else:
        lines.append("| Severity | Category | Location | Change |")
        lines.append("|---|---|---|---|")
        for c in changes:
            lines.append(f"| {c.severity} | {c.category} | `{c.location}` | {c.message} |")
    return "\n".join(lines)
