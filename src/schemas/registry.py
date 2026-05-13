"""Schema registry and validators.

The registry maps a schema-name (string) to a JSON-schema-like dict and
provides validate / validate_lenient helpers. We avoid the `jsonschema`
package dependency by implementing the small subset of draft-7 we need:
type, required, properties, items, enum, additionalProperties, oneOf.
"""
from __future__ import annotations

from typing import Any


SCHEMAS: dict[str, dict] = {}


class SchemaViolation(ValueError):
    """Raised by `validate` when a payload doesn't match its schema."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def register(name: str, schema: dict) -> None:
    """Register a schema under `name`. Overwrites any prior registration."""
    SCHEMAS[name] = schema


# ─────────────────────────────────────────────────────────────────────────
# Minimal draft-7 validator
# ─────────────────────────────────────────────────────────────────────────

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _check(payload: Any, schema: dict, path: str, errors: list[str]) -> None:
    """Recursive walker that appends violations to `errors` rather than
    raising. The strict / lenient wrappers handle the dispatch."""

    # oneOf: payload must satisfy exactly one branch (we accept first match)
    if "oneOf" in schema:
        sub_errors = []
        matched = False
        for branch in schema["oneOf"]:
            local = []
            _check(payload, branch, path, local)
            if not local:
                matched = True
                break
            sub_errors.append(local)
        if not matched:
            errors.append(
                f"{path}: did not match any oneOf branch "
                f"(first branch errors: {sub_errors[0] if sub_errors else '?'})"
            )
        return

    # type
    if "type" in schema:
        expected = schema["type"]
        if isinstance(expected, list):
            valid = any(isinstance(payload, _TYPE_MAP.get(t, object)) for t in expected)
        else:
            valid = isinstance(payload, _TYPE_MAP.get(expected, object))
            # bool is subclass of int in python; reject silently when we
            # asked for integer/number but got bool.
            if expected in ("integer", "number") and isinstance(payload, bool):
                valid = False
        if not valid:
            errors.append(
                f"{path}: expected type {expected!r}, got "
                f"{type(payload).__name__}"
            )
            return  # downstream checks would compound the same error

    # enum
    if "enum" in schema:
        if payload not in schema["enum"]:
            errors.append(
                f"{path}: value {payload!r} not in enum {schema['enum']!r}"
            )

    # object: required + properties
    if isinstance(payload, dict):
        for req in schema.get("required", []):
            if req not in payload:
                errors.append(f"{path}.{req}: required field missing")
        for k, sub in (schema.get("properties") or {}).items():
            if k in payload:
                _check(payload[k], sub, f"{path}.{k}", errors)
        # additionalProperties: defaults to True (permissive). Set to a
        # schema to constrain extras; set to False to forbid them.
        ap = schema.get("additionalProperties", True)
        if ap is False:
            allowed = set((schema.get("properties") or {}).keys())
            for k in payload:
                if k not in allowed:
                    errors.append(f"{path}.{k}: extra property not allowed")
        elif isinstance(ap, dict):
            allowed = set((schema.get("properties") or {}).keys())
            for k, v in payload.items():
                if k not in allowed:
                    _check(v, ap, f"{path}.{k}", errors)

    # array: items
    if isinstance(payload, list) and "items" in schema:
        item_schema = schema["items"]
        for i, item in enumerate(payload):
            _check(item, item_schema, f"{path}[{i}]", errors)

    # number bounds
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        if "minimum" in schema and payload < schema["minimum"]:
            errors.append(
                f"{path}: value {payload} < minimum {schema['minimum']}"
            )
        if "maximum" in schema and payload > schema["maximum"]:
            errors.append(
                f"{path}: value {payload} > maximum {schema['maximum']}"
            )


def validate(name: str, payload: Any) -> Any:
    """Strict validation: raises SchemaViolation on the first error.

    Use in tests and for outputs we trust to be schema-clean. For
    production LLM outputs (which can produce unexpected shapes) prefer
    `validate_lenient`.
    """
    if name not in SCHEMAS:
        raise KeyError(f"No schema registered under name {name!r}")
    errors: list[str] = []
    _check(payload, SCHEMAS[name], "$", errors)
    if errors:
        raise SchemaViolation(errors[0].split(":")[0], "; ".join(errors))
    return payload


def validate_lenient(name: str, payload: Any) -> tuple[bool, list[str]]:
    """Lenient validation: returns (ok, errors). Doesn't raise.

    Production callers should log non-empty errors to gazettes and
    proceed with a deterministic fallback. This converts a class of
    silent prompt/parser drift into a visible operational signal.
    """
    if name not in SCHEMAS:
        return False, [f"$: no schema registered under name {name!r}"]
    errors: list[str] = []
    _check(payload, SCHEMAS[name], "$", errors)
    return (not errors), errors


# ─────────────────────────────────────────────────────────────────────────
# Built-in schemas (registered on import via .definitions)
# ─────────────────────────────────────────────────────────────────────────

# Importing definitions populates SCHEMAS as a side effect.
from . import definitions  # noqa: E402,F401
