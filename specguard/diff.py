"""Compute the classified diff between two resolved OpenAPI documents.

Classification philosophy (documented, conservative where clients are hurt):

- Anything that can break an *existing, working* client is BREAKING:
  removed endpoints, removed parameters, new *required* inputs, narrowed
  types/enums, removed response fields.
- Anything purely additive is NON-BREAKING: new endpoints, new optional
  inputs, new response fields, new response codes.
- Ambiguous or cosmetic changes (``operationId`` renames, ``format``
  tweaks, complex ``allOf``/``oneOf`` reshuffles) are INFO — surfaced for a
  human, never failed on by default.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .model import Endpoint, normalize

BREAKING = "breaking"
NON_BREAKING = "non-breaking"
INFO = "info"

_SEVERITY_RANK = {BREAKING: 0, NON_BREAKING: 1, INFO: 2}
_COMPOSITION_KEYS = ("allOf", "oneOf", "anyOf", "not")


@dataclass
class Change:
    severity: str   # breaking | non-breaking | info
    category: str   # endpoint | parameter | request-body | response | schema | operation
    location: str   # e.g. "POST /tasks" or "GET /tasks/{id} response 200.properties.title"
    message: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "location": self.location,
            "message": self.message,
        }


def _hashable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, sort_keys=True)


def diff_specs(old_doc: dict, new_doc: dict) -> list[Change]:
    old_eps = normalize(old_doc)
    new_eps = normalize(new_doc)
    changes: list[Change] = []

    for path, method in sorted(set(old_eps) - set(new_eps)):
        changes.append(Change(BREAKING, "endpoint", f"{method} {path}",
                              f"Endpoint removed: {method} {path}"))
    for path, method in sorted(set(new_eps) - set(old_eps)):
        changes.append(Change(NON_BREAKING, "endpoint", f"{method} {path}",
                              f"Endpoint added: {method} {path}"))
    for key in sorted(set(old_eps) & set(new_eps)):
        changes.extend(_diff_endpoint(old_eps[key], new_eps[key]))

    changes.sort(key=lambda c: (_SEVERITY_RANK[c.severity], c.location))
    return changes


def _diff_endpoint(old: Endpoint, new: Endpoint) -> list[Change]:
    loc = f"{old.method} {old.path}"
    changes: list[Change] = []
    if old.operation_id != new.operation_id:
        changes.append(Change(INFO, "operation", loc,
                              f"operationId changed from {old.operation_id!r} to {new.operation_id!r}"))
    changes.extend(_diff_parameters(old.parameters, new.parameters, loc))
    changes.extend(_diff_request_body(old, new, loc))
    changes.extend(_diff_responses(old, new, loc))
    return changes


def _param_key(p) -> tuple:
    return (p.location, p.name)


def _diff_parameters(old_params: list, new_params: list, loc: str) -> list[Change]:
    old_i = {_param_key(p): p for p in old_params}
    new_i = {_param_key(p): p for p in new_params}
    changes: list[Change] = []

    for key in sorted(set(old_i) - set(new_i)):
        p = old_i[key]
        changes.append(Change(BREAKING, "parameter", loc,
                              f"Parameter removed: {p.location} `{p.name}`"))
    for key in sorted(set(new_i) - set(old_i)):
        p = new_i[key]
        if p.required:
            changes.append(Change(BREAKING, "parameter", loc,
                                  f"Required parameter added: {p.location} `{p.name}`"))
        else:
            changes.append(Change(NON_BREAKING, "parameter", loc,
                                  f"Optional parameter added: {p.location} `{p.name}`"))
    for key in sorted(set(old_i) & set(new_i)):
        op_, np_ = old_i[key], new_i[key]
        ploc = f"{loc} parameter `{op_.name}` ({op_.location})"
        if not op_.required and np_.required:
            changes.append(Change(BREAKING, "parameter", ploc, "Parameter became required"))
        elif op_.required and not np_.required:
            changes.append(Change(NON_BREAKING, "parameter", ploc, "Parameter became optional"))
        changes.extend(_diff_schema(op_.schema, np_.schema, ploc, "request"))
    return changes


def _diff_request_body(old: Endpoint, new: Endpoint, loc: str) -> list[Change]:
    changes: list[Change] = []
    bloc = f"{loc} request body"
    if not old.request_body_required and new.request_body_required:
        changes.append(Change(BREAKING, "request-body", bloc, "Request body became required"))
    elif old.request_body_required and not new.request_body_required:
        changes.append(Change(NON_BREAKING, "request-body", bloc, "Request body became optional"))
    if old.request_body_schema is not None or new.request_body_schema is not None:
        changes.extend(_diff_schema(old.request_body_schema, new.request_body_schema, bloc, "request"))
    return changes


def _diff_responses(old: Endpoint, new: Endpoint, loc: str) -> list[Change]:
    changes: list[Change] = []
    for code in sorted(set(old.responses) - set(new.responses)):
        changes.append(Change(BREAKING, "response", loc, f"Response removed: HTTP {code}"))
    for code in sorted(set(new.responses) - set(old.responses)):
        changes.append(Change(NON_BREAKING, "response", loc, f"Response added: HTTP {code}"))
    for code in sorted(set(old.responses) & set(new.responses)):
        old_s, new_s = old.responses[code], new.responses[code]
        if old_s is not None or new_s is not None:
            changes.extend(_diff_schema(old_s, new_s, f"{loc} response {code}", "response"))
    return changes


def _diff_schema(old: dict | None, new: dict | None, location: str, context: str) -> list[Change]:
    """Recursively diff two JSON-schema dicts.

    ``context`` is "request" (client -> server: strict about new requirements)
    or "response" (server -> client: strict about removed fields).
    """
    old = old or {}
    new = new or {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        if old != new:
            return [Change(BREAKING, "schema", location, f"Schema changed at {location}")]
        return []
    if old == new:
        return []
    changes: list[Change] = []

    if any(k in old or k in new for k in _COMPOSITION_KEYS):
        # allOf/oneOf reshuffles are hard to classify soundly; surface for review.
        changes.append(Change(INFO, "schema", location,
                              f"Schema composition changed at {location} — review manually"))
        return changes

    old_type, new_type = old.get("type"), new.get("type")
    if old_type != new_type:
        changes.append(Change(BREAKING, "schema", location,
                              f"Type changed from {old_type!r} to {new_type!r} at {location}"))
        return changes  # don't cascade noise into a value whose type already changed

    old_fmt, new_fmt = old.get("format"), new.get("format")
    if old_fmt != new_fmt:
        changes.append(Change(INFO, "schema", location,
                              f"Format changed from {old_fmt!r} to {new_fmt!r} at {location}"))

    old_enum = {_hashable(v) for v in (old.get("enum") or [])}
    new_enum = {_hashable(v) for v in (new.get("enum") or [])}
    removed_values = sorted(old_enum - new_enum, key=str)
    added_values = sorted(new_enum - old_enum, key=str)
    if removed_values:
        changes.append(Change(BREAKING, "schema", location,
                              f"Enum values removed at {location}: {removed_values}"))
    if added_values:
        changes.append(Change(NON_BREAKING, "schema", location,
                              f"Enum values added at {location}: {added_values}"))

    # OpenAPI 3.0: nullable defaults to false.
    if old.get("nullable", False) and not new.get("nullable", False):
        changes.append(Change(BREAKING, "schema", location,
                              f"Field became non-nullable at {location}"))
    elif not old.get("nullable", False) and new.get("nullable", False):
        changes.append(Change(NON_BREAKING, "schema", location,
                              f"Field became nullable at {location}"))

    old_req, new_req = set(old.get("required") or []), set(new.get("required") or [])
    added_req, removed_req = new_req - old_req, old_req - new_req
    for name in sorted(added_req):
        if context == "request":
            changes.append(Change(BREAKING, "schema", location,
                                  f"Required property added at {location}: `{name}`"))
        else:
            changes.append(Change(NON_BREAKING, "schema", location,
                                  f"Property marked required at {location}: `{name}`"))
    for name in sorted(removed_req):
        changes.append(Change(NON_BREAKING, "schema", location,
                              f"Property no longer required at {location}: `{name}`"))

    old_props, new_props = old.get("properties") or {}, new.get("properties") or {}
    for name in sorted(set(old_props) - set(new_props)):
        if context == "request":
            # Servers conventionally ignore unknown fields; removing a documented
            # request property rarely breaks working clients.
            changes.append(Change(NON_BREAKING, "schema", location,
                                  f"Request property removed at {location}: `{name}`"))
        else:
            changes.append(Change(BREAKING, "schema", location,
                                  f"Response property removed at {location}: `{name}`"))
    for name in sorted(set(new_props) - set(old_props)):
        if name in added_req:
            continue  # already reported above with the right severity
        changes.append(Change(NON_BREAKING, "schema", location,
                              f"Property added at {location}: `{name}`"))
    for name in sorted(set(old_props) & set(new_props)):
        changes.extend(_diff_schema(old_props[name], new_props[name], f"{location}.{name}", context))

    if "items" in old or "items" in new:
        changes.extend(_diff_schema(old.get("items"), new.get("items"), f"{location}[]", context))

    if context == "request":
        old_ap, new_ap = old.get("additionalProperties", True), new.get("additionalProperties", True)
        if old_ap and not new_ap:
            changes.append(Change(BREAKING, "schema", location,
                                  f"Additional properties disallowed at {location}"))
        elif not old_ap and new_ap:
            changes.append(Change(NON_BREAKING, "schema", location,
                                  f"Additional properties allowed at {location}"))

    return changes
