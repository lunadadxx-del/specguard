"""Loading OpenAPI documents and resolving internal ``$ref`` pointers.

Only internal references (``#/components/...``) are supported. External
references (files, URLs) raise :class:`SpecError` — silently fetching remote
schemas during a CI diff would be a supply-chain footgun, so this is a
deliberate limitation, documented in the README.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml


class SpecError(Exception):
    """Raised when a spec cannot be loaded, parsed, or resolved."""


def load_spec(path: str | Path) -> dict:
    """Load a YAML or JSON OpenAPI document from disk."""
    p = Path(path)
    if not p.exists():
        raise SpecError(f"spec file not found: {p}")
    text = p.read_text(encoding="utf-8")
    doc = None
    # JSON is valid YAML, but try JSON first for a sharper error on junk.
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"could not parse {p}: {exc}") from exc
    if not isinstance(doc, dict):
        raise SpecError(f"spec root must be a mapping, got {type(doc).__name__}")
    return doc


class RefResolver:
    """Recursively resolve internal ``$ref`` pointers in a loaded document."""

    def __init__(self, doc: dict):
        self.doc = doc
        self._cache: dict[str, object] = {}
        self._stack: set[str] = set()

    def resolve(self, node: object) -> object:
        return self._resolve(node)

    def _resolve(self, node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if not isinstance(ref, str) or not ref.startswith("#/"):
                    raise SpecError(f"only internal $refs are supported, got: {ref!r}")
                if ref in self._stack:
                    return {}  # recursive schema: break the cycle, keep going
                if ref in self._cache:
                    resolved = self._cache[ref]
                else:
                    self._stack.add(ref)
                    try:
                        resolved = self._resolve(self._lookup(ref))
                    finally:
                        self._stack.discard(ref)
                    self._cache[ref] = resolved
                # OpenAPI 3.1 allows siblings next to $ref; merge them over.
                siblings = {k: self._resolve(v) for k, v in node.items() if k != "$ref"}
                if isinstance(resolved, dict):
                    merged = dict(resolved)
                    merged.update(siblings)
                    return merged
                return resolved
            return {k: self._resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [self._resolve(item) for item in node]
        return node

    def _lookup(self, ref: str) -> object:
        node: object = self.doc
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")  # JSON pointer unescape
            if not isinstance(node, dict) or part not in node:
                raise SpecError(f"unresolvable $ref: {ref}")
            node = node[part]
        return node
