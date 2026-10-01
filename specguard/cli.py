"""Command-line interface.

Exit codes (CI-friendly):
    0 — success; changes are below the --fail-on threshold
    1 — usage / load / parse error
    2 — changes met or exceeded the --fail-on threshold
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__
from .diff import BREAKING, diff_specs
from .parser import RefResolver, SpecError, load_spec
from .report import render_json, render_markdown, render_text, summarize

FORMATS = {"text": render_text, "json": render_json, "markdown": render_markdown}


def load_ignore_rules(path: str) -> list[dict]:
    """Load ignore rules: a YAML list of {path, method, contains} mappings.

    A change is ignored when *all* keys present in a rule match it.
    """
    try:
        rules = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    except Exception as exc:
        raise SpecError(f"cannot read ignore file {path}: {exc}") from exc
    if not isinstance(rules, list):
        raise SpecError(f"ignore file {path} must contain a YAML list")
    return [r for r in rules if isinstance(r, dict)]


def _ignored(change, rules: list[dict]) -> bool:
    for rule in rules:
        if rule.get("path") and rule["path"] not in change.location:
            continue
        if rule.get("method") and rule["method"].upper() not in change.location.upper():
            continue
        if rule.get("contains") and rule["contains"].lower() not in (
            change.message + " " + change.location
        ).lower():
            continue
        return True
    return False


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="specguard",
        description="Detect breaking changes between two OpenAPI specifications.",
    )
    ap.add_argument("old", help="baseline OpenAPI spec (YAML or JSON)")
    ap.add_argument("new", help="new OpenAPI spec (YAML or JSON)")
    ap.add_argument("-f", "--format", choices=sorted(FORMATS), default="text",
                    help="output format (default: text)")
    ap.add_argument("--fail-on", choices=["breaking", "any", "never"], default="breaking",
                    help="which changes fail the run with exit code 2 (default: breaking)")
    ap.add_argument("--ignore", metavar="FILE",
                    help="YAML file with ignore rules ({path, method, contains})")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw_old, raw_new = load_spec(args.old), load_spec(args.new)
        old_doc = RefResolver(raw_old).resolve(raw_old)
        new_doc = RefResolver(raw_new).resolve(raw_new)
        changes = diff_specs(old_doc, new_doc)
        if args.ignore:
            rules = load_ignore_rules(args.ignore)
            changes = [c for c in changes if not _ignored(c, rules)]
        print(FORMATS[args.format](changes))
        if args.fail_on == "never":
            return 0
        counts = summarize(changes)
        if args.fail_on == "any" and changes:
            return 2
        if args.fail_on == "breaking" and counts[BREAKING]:
            return 2
        return 0
    except SpecError as exc:
        print(f"specguard: error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
