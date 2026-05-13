"""Schema validation for LLM-agent JSON outputs.

Wave ν+10 item 2: prompts and parsers drift apart over time. We build a
schema layer so the contract between each agent's prompt and its consumer
is explicit and testable. Bug H1 in Wave ν+9 (the rd_outcomes parse bug
that suppressed every generation transition for an entire 80-quarter run)
would have been caught at the first quarter by a schema validation step.

Each agent's expected JSON output is declared as a python dict that
follows draft-7 JSON-schema. The `validate(name, payload)` helper either
returns the payload (possibly with normalized fields) or raises
SchemaViolation with the offending path and a clear message. Callers
that want soft validation (warn, don't fail) use `validate_lenient`.

Design choices:

  * Schemas are deliberately PERMISSIVE on extra fields (additionalProperties
    True) so that experimental prompts can carry richer payloads without
    breaking the parser. They are STRICT on required fields and types.

  * Schemas live in code, not JSON files: keeps them next to the prompts
    and parsers that depend on them, and makes refactors trackable.

  * `validate_lenient` returns (ok, errors) so a caller can log violations
    to gazettes while still falling through to a deterministic fallback.
    This is the recommended call for production paths; use the strict
    `validate` only in tests.
"""
from __future__ import annotations

from typing import Any
from .registry import (
    SCHEMAS,
    SchemaViolation,
    validate,
    validate_lenient,
    register,
)

__all__ = [
    "SCHEMAS",
    "SchemaViolation",
    "validate",
    "validate_lenient",
    "register",
]
