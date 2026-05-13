"""Shared parsing helpers for defensive coercion of LLM-returned values.

Wave ν+9 Bug M6: investment_bank.py defined a defensive `_parse_float`
helper while commercial_bank.py used bare `float(...)`, so a malformed
LLM response that the investment bank tolerated would crash the
commercial bank. Consolidating the helper here keeps the contract
consistent across all financial-intermediary agents.
"""
from __future__ import annotations


def parse_float(v, default: float = 0.0) -> float:
    """Coerce ``v`` to float; return ``default`` if coercion fails.

    Tolerates the common LLM failure modes:
    - ``None`` (returns default)
    - empty string (returns default)
    - non-numeric strings (returns default)
    - dollar-formatted strings (e.g. ``"$1,234.56"``)
    """
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("$", "").replace(",", "")
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_int(v, default: int = 0) -> int:
    """Coerce ``v`` to int; return ``default`` if coercion fails."""
    f = parse_float(v, default=float("nan"))
    if f != f:  # NaN check
        return default
    return int(f)


def parse_bool(v, default: bool = False) -> bool:
    """Coerce ``v`` to bool; tolerates LLM's "true"/"yes"/"1"/"y" idioms."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "yes", "y", "1"}:
            return True
        if s in {"false", "no", "n", "0", ""}:
            return False
    return default
