"""
Wave θ: LLM call telemetry (token counts, latency, error counts).

Backends that support usage tracking (OpenRouter, MiniMax — both return
OpenAI-compatible `usage` blocks) call `record_call()` after each
successful response. The data is aggregated per run and written to:
  - `outputs/<run>/cost_summary.txt` — human-readable per-model rollup
  - `outputs/<run>/llm_calls.jsonl` — one line per call for detailed audit

Rationale: before committing to a multi-hour multi-seed run, researchers
need visibility into per-quarter token usage to budget and to diagnose
runaway agents. Token counts alone are valuable; $ pricing is model-
specific and left to downstream tooling.
"""

from __future__ import annotations

import contextvars
import json
import time
from pathlib import Path


# Per-thread (ContextVar-based so it plays well with ThreadPoolExecutor)
# agent_role tag. Set via `set_role()` context manager; read by backends
# via `current_role()`. Used to attribute tokens per agent role.
_current_role: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_role", default=""
)


def current_role() -> str:
    return _current_role.get()


class set_role:
    """Context manager that tags LLM calls inside the block with a role.

    Usage:
        with set_role("firm_0"):
            result = backend.complete(system, user)

    Works across threads when the caller uses `copy_context().run()`
    (standard ThreadPoolExecutor context propagation).
    """

    def __init__(self, role: str):
        self._role = role
        self._token = None

    def __enter__(self):
        self._token = _current_role.set(self._role)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _current_role.reset(self._token)
        return False


def tag_backend(backend, role: str):
    """Wrap a backend so every call it serves is tagged with `role`.

    Returns a thin proxy that forwards .complete() and .complete_json()
    through a `set_role(role)` context manager. Attributes like `.model`,
    `.temperature` pass through via __getattr__. Use this at agent
    factory sites in cli.py to avoid touching every make_* body.

    Wave ν+10: also wraps the underlying backend with LoggingBackend so
    full prompts + responses are captured to disk on quarters where
    prompt_logger is active. The role-tag wrapper sits OUTSIDE the
    logging wrapper so the role ContextVar is already set by the time
    the logger reads it. When the logger is inactive (default in every
    quarter except the scheduled ones), it's a single boolean check.
    """

    # Apply prompt-logging wrap first (innermost).
    try:
        from .prompt_logger import LoggingBackend
        inner = LoggingBackend(backend, fallback_role=role)
    except Exception:
        # If the logger fails to import, fall back to raw backend.
        inner = backend

    class _RoleTagged:
        def complete(self, system, user):
            with set_role(role):
                return inner.complete(system, user)

        def complete_json(self, system, user, retries=2):
            with set_role(role):
                return inner.complete_json(system, user, retries=retries)

        def __getattr__(self, item):
            return getattr(inner, item)

    return _RoleTagged()


class _Telemetry:
    """Per-process LLM telemetry accumulator (singleton).

    Intentionally simple: a list of per-call records plus aggregate
    counters. Thread-safe for append (GIL); no locking needed.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.start_time = time.time()
        # Model → {"prompt": $/1M_tokens, "completion": $/1M_tokens}
        # Loaded on-demand from OpenRouter API; missing models → no $ estimate.
        self.pricing: dict[str, dict] = {}
        self._pricing_fetched = False

    def fetch_pricing_openrouter(self) -> None:
        """Fetch OpenRouter pricing once at run start (cheap GET request)."""
        if self._pricing_fetched:
            return
        self._pricing_fetched = True
        try:
            import requests
            resp = requests.get(
                "https://openrouter.ai/api/v1/models",
                timeout=15,
            )
            if resp.status_code != 200:
                return
            body = resp.json()
            for m in body.get("data", []):
                mid = m.get("id", "")
                p = m.get("pricing", {}) or {}
                # OpenRouter returns strings like "0.000001" for $/token
                try:
                    prompt_cost = float(p.get("prompt", "0") or 0) * 1_000_000
                    completion_cost = float(p.get("completion", "0") or 0) * 1_000_000
                except (TypeError, ValueError):
                    continue
                self.pricing[mid] = {
                    "prompt_per_mtok": prompt_cost,
                    "completion_per_mtok": completion_cost,
                }
        except Exception:
            # Pricing is informational — never block a run.
            pass

    def record_call(self, *, model: str, input_tokens: int,
                    output_tokens: int, latency_ms: float = 0.0,
                    backend: str = "", agent_role: str = "") -> None:
        """Record one LLM call's usage stats."""
        self.calls.append({
            "t": time.time() - self.start_time,
            "model": model,
            "backend": backend,
            "agent_role": agent_role,
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "total_tokens": int(input_tokens + output_tokens),
            "latency_ms": int(latency_ms),
        })

    def reset(self) -> None:
        self.calls = []
        self.start_time = time.time()

    def _cost_usd(self, model: str, in_tok: int, out_tok: int) -> float:
        """Estimated $ cost using OpenRouter pricing (0 if unknown)."""
        p = self.pricing.get(model)
        if not p:
            return 0.0
        return (in_tok / 1_000_000.0) * p["prompt_per_mtok"] + \
               (out_tok / 1_000_000.0) * p["completion_per_mtok"]

    def summary(self) -> dict:
        """Compute aggregate stats per model and per agent_role."""
        by_model: dict[str, dict] = {}
        by_role: dict[str, dict] = {}
        for c in self.calls:
            m = c["model"]
            if m not in by_model:
                by_model[m] = {
                    "n_calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "total_tokens": 0, "sum_latency_ms": 0, "cost_usd": 0.0,
                }
            e = by_model[m]
            e["n_calls"] += 1
            e["input_tokens"] += c["input_tokens"]
            e["output_tokens"] += c["output_tokens"]
            e["total_tokens"] += c["total_tokens"]
            e["sum_latency_ms"] += c["latency_ms"]
            e["cost_usd"] += self._cost_usd(m, c["input_tokens"], c["output_tokens"])

            r = c.get("agent_role") or "unattributed"
            if r not in by_role:
                by_role[r] = {
                    "n_calls": 0, "total_tokens": 0, "cost_usd": 0.0,
                }
            br = by_role[r]
            br["n_calls"] += 1
            br["total_tokens"] += c["total_tokens"]
            br["cost_usd"] += self._cost_usd(m, c["input_tokens"], c["output_tokens"])

        total = {
            "n_calls": len(self.calls),
            "input_tokens": sum(c["input_tokens"] for c in self.calls),
            "output_tokens": sum(c["output_tokens"] for c in self.calls),
            "total_tokens": sum(c["total_tokens"] for c in self.calls),
            "wallclock_seconds": time.time() - self.start_time,
            "cost_usd": sum(e["cost_usd"] for e in by_model.values()),
        }
        return {"total": total, "by_model": by_model, "by_role": by_role}

    def dump(self, run_dir: str | Path) -> None:
        """Write telemetry to disk. No-op if no calls were recorded."""
        if not self.calls:
            return
        base = Path(run_dir)
        base.mkdir(parents=True, exist_ok=True)
        # Per-call detail
        with open(base / "llm_calls.jsonl", "w", encoding="utf-8") as f:
            for c in self.calls:
                f.write(json.dumps(c) + "\n")
        # Human-readable summary
        s = self.summary()
        lines = []
        lines.append("=== LLM COST / TOKEN SUMMARY ===")
        lines.append(f"Total calls: {s['total']['n_calls']:,}")
        lines.append(f"Total input tokens:  {s['total']['input_tokens']:,}")
        lines.append(f"Total output tokens: {s['total']['output_tokens']:,}")
        lines.append(f"Total tokens:        {s['total']['total_tokens']:,}")
        lines.append(f"Wallclock:           {s['total']['wallclock_seconds']:.1f}s")
        if s["total"]["cost_usd"] > 0:
            lines.append(f"Estimated cost:      ${s['total']['cost_usd']:.4f} USD")
        lines.append("")
        lines.append("Per-model breakdown:")
        for m, e in sorted(s["by_model"].items(),
                            key=lambda x: -x[1]["total_tokens"]):
            avg_lat = (e["sum_latency_ms"] / e["n_calls"]) if e["n_calls"] else 0
            cost_str = (f"   cost=${e['cost_usd']:.4f}"
                        if e["cost_usd"] > 0 else "   cost=n/a")
            lines.append(f"  {m}")
            lines.append(f"    calls={e['n_calls']:>5,}   "
                         f"in={e['input_tokens']:>9,}   "
                         f"out={e['output_tokens']:>8,}   "
                         f"total={e['total_tokens']:>9,}   "
                         f"avg_lat={avg_lat:>6.0f}ms{cost_str}")
        lines.append("")
        lines.append("Per-agent-role breakdown:")
        for r, e in sorted(s["by_role"].items(),
                            key=lambda x: -x[1]["total_tokens"]):
            cost_str = (f"   cost=${e['cost_usd']:.4f}"
                        if e["cost_usd"] > 0 else "   cost=n/a")
            lines.append(f"  {r:22s}  calls={e['n_calls']:>5,}   "
                         f"tokens={e['total_tokens']:>9,}{cost_str}")
        with open(base / "cost_summary.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


# Singleton
_telemetry = _Telemetry()


def record_call(**kwargs) -> None:
    _telemetry.record_call(**kwargs)


def reset() -> None:
    _telemetry.reset()


def summary() -> dict:
    return _telemetry.summary()


def dump(run_dir: str | Path) -> None:
    _telemetry.dump(run_dir)


def fetch_pricing_openrouter() -> None:
    """Load OpenRouter pricing table once at run start (no-op if cached)."""
    _telemetry.fetch_pricing_openrouter()
