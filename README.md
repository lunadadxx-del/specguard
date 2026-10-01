# specguard

**Detect breaking API changes before your clients do.**

`specguard` diffs two OpenAPI specifications (YAML or JSON) and classifies every
change as **breaking**, **non-breaking**, or **informational** — with CI-friendly
exit codes so a breaking change can fail your pipeline before it ships.

## Problem statement

Most API breakages are not dramatic rewrites. They are quiet contract edits:
a removed query parameter, a new *required* field in a request body, a narrowed
enum, a deleted response field. These slip through code review because the diff
of two 3,000-line YAML files is unreadable, and the team that discovers the
breakage is the client team — in production.

Existing options are either language-specific linters or heavyweight
governance platforms. Teams need a small, dependency-light tool that answers
one question in CI: *"does this spec change break existing clients?"*

## Solution

`specguard` parses both specs, resolves internal `$ref`s, normalizes every
operation into a comparable endpoint model, then recursively diffs parameters,
request bodies, and response schemas — applying a documented set of
compatibility rules to classify each change. Output is human-readable text,
JSON for tooling, or Markdown for PR comments.

## Features

- **Breaking-change classification** — recursive schema diff with rules for
  endpoints, parameters, request bodies, responses, enums, nullability,
  `required` sets, and `additionalProperties`
- **Internal `$ref` resolution** — shared `components/schemas` are expanded
  before diffing, with cycle protection for recursive schemas
- **Three output formats** — `text` (human), `json` (tooling), `markdown` (PR comments)
- **CI exit codes** — `0` clean, `2` threshold exceeded (`--fail-on breaking|any|never`), `1` error
- **Ignore rules** — YAML allowlist (`{path, method, contains}`) for accepted/legacy changes
- **Zero-config** — single dependency (`pyyaml`), Python 3.9+

## Classification rules

| Change | Severity | Rationale |
|---|---|---|
| Endpoint removed | breaking | existing clients call it |
| Required parameter / required body field added | breaking | old requests become invalid |
| Parameter removed | breaking | contract shrank |
| Parameter became required | breaking | old requests become invalid |
| Type changed | breaking | deserialization breaks |
| Enum values removed | breaking | previously valid values rejected |
| Field became non-nullable | breaking | null payloads rejected |
| Response field removed | breaking | clients may read it |
| Response code removed | breaking | clients may handle it |
| `additionalProperties` disallowed (request) | breaking | extra fields now rejected |
| Endpoint / optional parameter / response field added | non-breaking | purely additive |
| Enum values widened | non-breaking | old values still valid |
| Request property removed | non-breaking | servers conventionally ignore unknown fields |
| `operationId` renamed, `format` tweaked | info | cosmetic / needs human eyes |
| `allOf`/`oneOf` reshuffled | info | classified conservatively; review manually |

## Architecture

```
spec text → parser (load YAML/JSON, resolve $refs)
          → model  (normalize to {(path, method): Endpoint})
          → diff   (recursive compare + classify → [Change])
          → report (text / json / markdown)
          → cli    (argparse, ignore rules, exit codes)
```

- `specguard/parser.py` — file loading and internal `$ref` resolution (external
  refs are rejected deliberately: silently fetching remote schemas in CI is a
  supply-chain risk)
- `specguard/model.py` — flattens operations into `Endpoint` records; merges
  path-level and operation-level parameters; prefers `application/json` media types
- `specguard/diff.py` — the rule engine: endpoint set-diff, parameter diff,
  request/response body diff, and a recursive JSON-schema differ that tracks a
  `request` vs `response` context (strictness differs by direction)
- `specguard/report.py` — renderers
- `specguard/cli.py` — argument parsing, ignore-rule filtering, exit codes

## Tech stack

- Python 3.9+
- `pyyaml` (only runtime dependency)
- Standard library otherwise (`argparse`, `unittest`, `dataclasses`)

## Project structure

```
specguard/
├── specguard/
│   ├── __init__.py
│   ├── __main__.py      # python -m specguard
│   ├── parser.py        # load + $ref resolution
│   ├── model.py         # endpoint normalization
│   ├── diff.py          # recursive diff + classification
│   ├── report.py        # text/json/markdown renderers
│   └── cli.py           # CLI, ignore rules, exit codes
├── tests/
│   ├── test_parser.py   # loading, $ref, cycles, error cases
│   ├── test_diff.py     # classification rules
│   └── test_cli.py      # end-to-end CLI, formats, exit codes
├── examples/
│   ├── v1.yaml          # Taskly API v1.4.0
│   ├── v2.yaml          # Taskly API v2.0.0 (8 breaking changes)
│   └── ignore-example.yaml
├── pyproject.toml
├── README.md
├── LICENSE
└── .gitignore
```

## Setup

```bash
git clone https://github.com/lunadadxx-del/specguard.git
cd specguard
pip install -e .        # or: pip install pyyaml   (then use python -m specguard)
```

No API keys. No network access. No environment variables — the tool reads two
local files and prints a report.

## How to run

```bash
# basic diff (fails with exit code 2 if breaking changes found)
specguard old.yaml new.yaml

# JSON output for tooling
specguard old.yaml new.yaml --format json > changes.json

# Markdown report (paste into a PR)
specguard old.yaml new.yaml --format markdown > report.md

# fail the build on ANY change, or never fail (report only)
specguard old.yaml new.yaml --fail-on any
specguard old.yaml new.yaml --fail-on never

# ignore known-acceptable changes
specguard old.yaml new.yaml --ignore ignore.yaml
```

## Example usage

The `examples/` directory contains two versions of a fictional "Taskly" API.
v2.0.0 removes an endpoint, adds a required query parameter, narrows an enum,
adds a required request field, and drops a response field:

```bash
$ specguard examples/v1.yaml examples/v2.yaml
specguard: 8 breaking, 3 non-breaking, 1 informational

== BREAKING (8) ==
  [endpoint] DELETE /tasks/{id}
      Endpoint removed: DELETE /tasks/{id}
  [parameter] GET /tasks
      Parameter removed: query `limit`
  [parameter] GET /tasks
      Required parameter added: query `workspace_id`
  [schema] GET /tasks response 200[]
      Response property removed at GET /tasks response 200[]: `created_at`
  [schema] GET /tasks/{id} response 200
      Response property removed at GET /tasks/{id} response 200: `created_at`
  [schema] POST /tasks request body
      Required property added at POST /tasks request body: `due_date`
  [schema] POST /tasks request body.priority
      Enum values removed at POST /tasks request body.priority: ['medium']
  [schema] POST /tasks response 201
      Response property removed at POST /tasks response 201: `created_at`

== NON-BREAKING (3) ==
  [endpoint] GET /health
      Endpoint added: GET /health
  [parameter] GET /tasks
      Optional parameter added: query `sort`
  [response] POST /tasks
      Response added: HTTP 429

== INFO (1) ==
  [operation] GET /tasks
      operationId changed from 'listTasks' to 'listAllTasks'
$ echo $?
2
```

### Use in CI (GitHub Actions)

```yaml
- name: Check for breaking API changes
  run: |
    pip install specguard
    specguard specs/openapi.base.yaml specs/openapi.yaml --format markdown > api-diff.md
```

The step fails (exit 2) only when breaking changes are detected.

### Ignore file format

```yaml
# ignore.yaml — a change is ignored when ALL keys in a rule match it
- path: /health        # substring match on the change location
  method: GET
- contains: operationId # substring match on message + location
```

## Running the tests

```bash
python -m unittest discover -s tests
```

33 tests covering `$ref` resolution (including recursive schemas), every
classification rule, reporters, ignore rules, and CLI exit codes.

## Limitations (honest)

- Only **internal** `$ref`s (`#/components/...`) are resolved; external file/URL
  refs are rejected with a clear error.
- Only `application/json` (falling back to the first media type) is compared
  for request/response bodies.
- `allOf`/`oneOf`/`anyOf` reshuffles are reported as informational rather than
  deeply classified — compositional subtyping is undecidable in the general case
  and a wrong "breaking" verdict is worse than an honest "review manually".
- OpenAPI 3.0 semantics throughout (e.g. `nullable`); 3.1-style type arrays are
  compared structurally.

## Future improvements

- Deep `allOf` merge before diffing for common composition patterns
- `--baseline` mode: compare a spec against the last tagged release automatically
- SARIF output for native GitHub code-scanning integration
- Webhook mode: comment the Markdown report directly on the PR
- Support for AsyncAPI documents
