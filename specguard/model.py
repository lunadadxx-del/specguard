"""Normalized endpoint model extracted from a resolved OpenAPI document.

The differ works against this model instead of raw dicts so that
path-level vs operation-level parameters, media-type selection, and
``$ref``-resolved schemas are handled in exactly one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}


@dataclass
class Parameter:
    name: str
    location: str  # query | header | path | cookie
    required: bool
    schema: dict


@dataclass
class Endpoint:
    path: str
    method: str  # upper-cased, e.g. "GET"
    operation_id: str | None
    parameters: list[Parameter] = field(default_factory=list)
    request_body_required: bool = False
    request_body_schema: dict | None = None
    responses: dict[str, dict | None] = field(default_factory=dict)  # status -> schema


def _merge_parameters(shared: list, specific: list) -> list[dict]:
    """Path-level parameters act as defaults; operation-level ones win."""
    merged: dict[tuple, dict] = {}
    for raw in list(shared or []) + list(specific or []):
        if isinstance(raw, dict) and raw.get("name"):
            merged[(raw.get("in"), raw.get("name"))] = raw
    return list(merged.values())


def _pick_schema(content: dict | None) -> dict | None:
    """Pick the schema for a request/response body, preferring JSON."""
    if not isinstance(content, dict) or not content:
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        media = next((v for v in content.values() if isinstance(v, dict)), {})
    schema = media.get("schema")
    return schema if isinstance(schema, dict) else None


def normalize(doc: dict) -> dict[tuple[str, str], Endpoint]:
    """Flatten an OpenAPI document into {(path, METHOD): Endpoint}."""
    endpoints: dict[tuple[str, str], Endpoint] = {}
    paths = doc.get("paths") or {}
    if not isinstance(paths, dict):
        return endpoints
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        shared_params = path_item.get("parameters") or []
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            params = [
                Parameter(
                    name=p.get("name", ""),
                    location=p.get("in", ""),
                    required=bool(p.get("required", False)),
                    schema=p.get("schema") if isinstance(p.get("schema"), dict) else {},
                )
                for p in _merge_parameters(shared_params, operation.get("parameters") or [])
            ]
            body = operation.get("requestBody") or {}
            responses: dict[str, dict | None] = {}
            for code, resp in (operation.get("responses") or {}).items():
                if isinstance(resp, dict):
                    responses[str(code)] = _pick_schema(resp.get("content"))
                else:
                    responses[str(code)] = None
            endpoints[(path, method.upper())] = Endpoint(
                path=path,
                method=method.upper(),
                operation_id=operation.get("operationId"),
                parameters=params,
                request_body_required=bool(body.get("required", False)),
                request_body_schema=_pick_schema(body.get("content")),
                responses=responses,
            )
    return endpoints
