"""
LLM backend abstraction. Each backend sends system+user prompts and returns text.

Supported backends:
- mock: deterministic, for testing
- openrouter: OpenRouter API (default: deepseek/deepseek-v3.2)
- minimax: MiniMax direct API (api.minimaxi.chat)
- aihorde: AI Horde crowdsourced cluster (async submit + poll)
- ollama: local Ollama instance
"""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod

import requests

from .config import LLMConfig


class LLMBackend(ABC):
    """Abstract LLM backend."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send system + user prompt, return raw text response."""

    def complete_json(self, system: str, user: str, retries: int = 2) -> dict | None:
        """Complete and extract JSON. Retry on parse failure."""
        for attempt in range(1 + retries):
            response = self.complete(system, user)
            result = extract_json(response)
            if result is not None:
                return result
            if attempt < retries:
                user = (
                    f"Your previous response did not contain valid JSON. "
                    f"Please output ONLY a JSON object wrapped in ```json ... ```.\n\n"
                    f"Original request:\n{user}"
                )
        return None


class MockBackend(LLMBackend):
    """Returns fixed responses for testing. No LLM calls."""

    def __init__(self, responses: dict[str, str] | None = None):
        self._responses = responses or {}
        self._call_count = 0

    def complete(self, system: str, user: str) -> str:
        self._call_count += 1
        # Check for specific response keyed by substring in user prompt
        for key, response in self._responses.items():
            if key in user:
                return response
        # Default: return a minimal valid firm decision
        return _DEFAULT_MOCK_RESPONSE


class OpenRouterBackend(LLMBackend):
    """OpenRouter API client."""

    def __init__(self, config: LLMConfig):
        self.model = config.model
        self.api_key = config.api_key
        self.temperature = config.temperature
        self.timeout = config.timeout_seconds
        if not self.api_key:
            raise ValueError(
                f"OpenRouter API key not found. Set {config.api_key_env} "
                f"environment variable."
            )

    def complete(self, system: str, user: str) -> str:
        max_retries = 5
        t_start = time.time()
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": self.temperature,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt * 3  # 3, 6, 12, 24, 48 seconds
                    print(f"    [{self.model}] Rate limited, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                # Parse JSON defensively: body may be HTML (gateway error) or truncated
                try:
                    body = resp.json()
                except (ValueError, requests.exceptions.JSONDecodeError) as e:
                    if attempt < max_retries - 1:
                        wait = 2 ** attempt * 2
                        print(f"    [{self.model}] Bad JSON response ({e}), "
                              f"retrying in {wait}s ({attempt+1}/{max_retries})")
                        time.sleep(wait)
                        continue
                    # Final failure: return empty string so caller's JSON-extraction
                    # retry logic kicks in rather than crashing the simulation.
                    print(f"    [{self.model}] Giving up on bad JSON; returning empty response")
                    return ""
                try:
                    content = body["choices"][0]["message"]["content"]
                    # Wave θ: record token usage for this call.
                    _record_usage(body, self.model, "openrouter", t_start)
                    return content
                except (KeyError, IndexError, TypeError) as e:
                    if attempt < max_retries - 1:
                        print(f"    [{self.model}] Malformed response shape ({e}), retrying")
                        time.sleep(2)
                        continue
                    print(f"    [{self.model}] Giving up on malformed response; returning empty")
                    return ""
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    print(f"    [{self.model}] Timeout, retrying ({attempt+1}/{max_retries})")
                    time.sleep(5)
                    continue
                raise
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    print(f"    [{self.model}] Connection error, retrying ({attempt+1}/{max_retries})")
                    time.sleep(5)
                    continue
                raise
        raise RuntimeError(f"[{self.model}] Failed after {max_retries} retries (rate limited)")


def _record_usage(body: dict, model: str, backend: str, t_start: float) -> None:
    """Extract OpenAI-compatible `usage` block and record to telemetry.

    Safe: silently no-ops if the block is missing or malformed.
    Picks up agent_role from the current ContextVar tag (`set_role()`).
    """
    try:
        usage = body.get("usage") or {}
        from . import telemetry as _tel
        _tel.record_call(
            model=model,
            backend=backend,
            agent_role=_tel.current_role(),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=(time.time() - t_start) * 1000.0,
        )
    except Exception:
        pass


class MiniMaxBackend(LLMBackend):
    """MiniMax direct API client (OpenAI-compatible)."""

    def __init__(self, config: LLMConfig):
        self.model = config.model  # e.g. "MiniMax-M1-80k"
        self.api_key = os.environ.get("MINIMAX_API_KEY", "")
        if not self.api_key:
            self.api_key = config.api_key  # fallback to config
        self.temperature = config.temperature
        self.timeout = config.timeout_seconds
        if not self.api_key:
            raise ValueError(
                "MiniMax API key not found. Set MINIMAX_API_KEY "
                "environment variable."
            )

    def complete(self, system: str, user: str) -> str:
        max_retries = 5
        t_start = time.time()
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    "https://api.minimaxi.chat/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": self.temperature,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt * 3
                    print(f"    [{self.model}] Rate limited, waiting {wait}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                try:
                    body = resp.json()
                except (ValueError, requests.exceptions.JSONDecodeError) as e:
                    if attempt < max_retries - 1:
                        wait = 2 ** attempt * 2
                        print(f"    [{self.model}] Bad JSON response ({e}), retrying in {wait}s")
                        time.sleep(wait)
                        continue
                    print(f"    [{self.model}] Giving up on bad JSON; returning empty")
                    return ""
                try:
                    content = body["choices"][0]["message"]["content"]
                    _record_usage(body, self.model, "minimax", t_start)
                    return content
                except (KeyError, IndexError, TypeError) as e:
                    if attempt < max_retries - 1:
                        print(f"    [{self.model}] Malformed response ({e}), retrying")
                        time.sleep(2)
                        continue
                    return ""
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    print(f"    [{self.model}] Timeout, retrying ({attempt+1}/{max_retries})")
                    time.sleep(5)
                    continue
                raise
            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    print(f"    [{self.model}] Connection error, retrying ({attempt+1}/{max_retries})")
                    time.sleep(5)
                    continue
                raise
        raise RuntimeError(f"[{self.model}] Failed after {max_retries} retries (rate limited)")


class AIHordeBackend(LLMBackend):
    """AI Horde crowdsourced text generation (async submit + poll)."""

    def __init__(self, config: LLMConfig):
        self.model = config.model
        self.api_key = os.environ.get("AIHORDE_API_KEY", "")
        if not self.api_key:
            self.api_key = config.api_key or ""
        self.temperature = config.temperature
        self.timeout = config.timeout_seconds
        if not self.api_key:
            raise ValueError(
                "AI Horde API key not found. Set AIHORDE_API_KEY "
                "environment variable."
            )

    def complete(self, system: str, user: str) -> str:
        prompt = f"### System:\n{system}\n\n### User:\n{user}\n\n### Assistant:\n"
        payload = {
            "prompt": prompt,
            "params": {"max_length": 1024, "temperature": self.temperature},
            "models": [self.model],
        }
        # Submit async
        resp = requests.post(
            "https://aihorde.net/api/v2/generate/text/async",
            json=payload,
            headers={"apikey": self.api_key},
            timeout=30,
        )
        if resp.status_code != 202:
            raise RuntimeError(
                f"[{self.model}] AI Horde submit failed: "
                f"{resp.status_code} {resp.text[:200]}"
            )
        job_id = resp.json()["id"]

        # Poll until done (max timeout_seconds)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(3)
            status = requests.get(
                f"https://aihorde.net/api/v2/generate/text/status/{job_id}",
                timeout=15,
            ).json()
            if status.get("done"):
                gens = status.get("generations", [])
                if gens:
                    return gens[0].get("text", "")
                raise RuntimeError(f"[{self.model}] AI Horde returned no generations")
        raise RuntimeError(f"[{self.model}] AI Horde timed out after {self.timeout}s")


class OllamaBackend(LLMBackend):
    """Local Ollama client."""

    def __init__(self, config: LLMConfig):
        self.model = config.model
        self.host = config.host
        self.temperature = config.temperature
        self.timeout = config.timeout_seconds

    def complete(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": self.temperature},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        try:
            return resp.json()["message"]["content"]
        except (ValueError, KeyError, requests.exceptions.JSONDecodeError):
            return ""


def create_backend(config: LLMConfig) -> LLMBackend:
    """Factory: create a backend from config."""
    if config.backend == "mock":
        return MockBackend()
    elif config.backend == "openrouter":
        return OpenRouterBackend(config)
    elif config.backend == "minimax":
        return MiniMaxBackend(config)
    elif config.backend == "aihorde":
        return AIHordeBackend(config)
    elif config.backend == "ollama":
        return OllamaBackend(config)
    else:
        raise ValueError(f"Unknown LLM backend: {config.backend}")


# ─── Wave ν+14e: BackupBackend chain ─────────────────────────────────────
#
# Problem: when an LLM backend fails (rate limit, timeout, malformed),
# every prior wave's response was either (a) return None and let the
# caller silently skip, or (b) retry the SAME backend N times then give
# up. Neither handles "the model has been having a bad hour": the firm
# decision / equity panel / pitch / etc. effectively goes missing for
# that quarter, the orchestrator silently moves forward, and the
# simulation's economic dynamics are subtly wrong.
#
# Per user direction (run-6 review): "NEVER move forward if missing,
# just move to next AI if repeated failure."
#
# BackupBackend wraps a PRIMARY backend with one or more BACKUPS.
# Its complete() / complete_json() try the primary first. On failure
# (empty string for complete, None for complete_json), it falls through
# to the next backup. Only returns failure when ALL backends have
# failed. This eliminates the silent-skip mode for any backend wrapped
# with backups.


class BackupBackend(LLMBackend):
    """Backend chain: try primary, then each backup in order on failure.

    On every layer's failure, prints a single diagnostic line so the
    operator can see when fallback activated. The chain itself never
    raises — it returns empty string from complete() or None from
    complete_json() ONLY when every backend in the chain has failed.

    Use case: wrap each role's backend with a chain like:
        BackupBackend(primary=OpenRouter(qwen-235b),
                      backups=[OpenRouter(llama-70b), OpenRouter(gpt-4o-mini)])
    """

    def __init__(self, primary: "LLMBackend", backups: list["LLMBackend"],
                  role_tag: str = ""):
        self.primary = primary
        self.backups = list(backups or [])
        self.role_tag = role_tag

    def _chain(self) -> list["LLMBackend"]:
        return [self.primary] + self.backups

    def _model_name(self, backend: "LLMBackend") -> str:
        # Unwrap LoggingBackend / role-tag wrappers if present
        b = backend
        for _ in range(5):
            inner = getattr(b, "wrapped", None) or getattr(b, "_inner", None)
            if inner is None:
                break
            b = inner
        return getattr(b, "model", b.__class__.__name__)

    def complete(self, system: str, user: str) -> str:
        for i, backend in enumerate(self._chain()):
            try:
                out = backend.complete(system, user)
            except Exception as e:
                tag = f"[{self.role_tag}] " if self.role_tag else ""
                print(f"    {tag}backup tier {i} ({self._model_name(backend)}) raised: {e}; falling to next",
                      flush=True)
                continue
            if out:
                if i > 0:
                    tag = f"[{self.role_tag}] " if self.role_tag else ""
                    print(f"    {tag}backup tier {i} ({self._model_name(backend)}) succeeded",
                          flush=True)
                return out
            # empty string → failure for complete()
            tag = f"[{self.role_tag}] " if self.role_tag else ""
            print(f"    {tag}backup tier {i} ({self._model_name(backend)}) returned empty; falling to next",
                  flush=True)
        return ""

    def complete_json(self, system: str, user: str, retries: int = 2) -> dict | None:
        for i, backend in enumerate(self._chain()):
            try:
                out = backend.complete_json(system, user, retries=retries)
            except Exception as e:
                tag = f"[{self.role_tag}] " if self.role_tag else ""
                print(f"    {tag}backup tier {i} ({self._model_name(backend)}) raised: {e}; falling to next",
                      flush=True)
                continue
            if out is not None:
                if i > 0:
                    tag = f"[{self.role_tag}] " if self.role_tag else ""
                    print(f"    {tag}backup tier {i} ({self._model_name(backend)}) succeeded",
                          flush=True)
                return out
            tag = f"[{self.role_tag}] " if self.role_tag else ""
            print(f"    {tag}backup tier {i} ({self._model_name(backend)}) returned None; falling to next",
                  flush=True)
        return None


def make_backup_chain(primary_cfg: "LLMConfig",
                       backup_cfgs: list["LLMConfig"] | None = None,
                       role_tag: str = "") -> "LLMBackend":
    """Convenience: build a BackupBackend from configs."""
    primary = create_backend(primary_cfg)
    backups = [create_backend(c) for c in (backup_cfgs or [])]
    if not backups:
        return primary  # no backups configured; just the primary
    return BackupBackend(primary, backups, role_tag=role_tag)


# Default backup pool — reliable OpenRouter models, diverse families,
# tried in this order whenever a role's primary backend persistently
# fails. Used by cli.py when wiring roles without explicit backup
# config. Cheap-ish, fast, and reliable on OpenRouter.
DEFAULT_BACKUP_MODELS: list[tuple[str, str]] = [
    # (model, openrouter_api_key_env_default)
    ("meta-llama/llama-3.3-70b-instruct", "OPENROUTER_API_KEY"),
    ("google/gemini-flash-1.5", "OPENROUTER_API_KEY"),
    ("qwen/qwen3-235b-a22b-2507", "OPENROUTER_API_KEY"),
]


def build_default_backup_pool(role_tag: str = "",
                                exclude_model: str = "") -> list["LLMBackend"]:
    """Build the default backup pool, optionally excluding a model
    (avoid duplicating the primary in its own backup chain).
    """
    from .config import LLMConfig as _LLMC
    backups: list["LLMBackend"] = []
    for model, env_var in DEFAULT_BACKUP_MODELS:
        if model == exclude_model:
            continue
        cfg = _LLMC(
            backend="openrouter",
            model=model,
            api_key_env=env_var,
            temperature=0.20,
        )
        try:
            backups.append(create_backend(cfg))
        except Exception:
            pass  # missing API key etc. — skip silently
    return backups


# ─── JSON extraction ─────────────────────────────────────────────────────

def extract_json(text: str) -> dict | None:
    """Extract the first JSON object from LLM response text."""
    # Try ```json ... ``` block first
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try first { ... } with brace counting
    depth = 0
    start = None
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


# ─── Default mock response ───────────────────────────────────────────────

_DEFAULT_MOCK_RESPONSE = '''```json
{
  "price": 92000,
  "production": 200,
  "capex": 15000000,
  "rd_spend": 25000000,
  "rd_allocation": {"product": 0.60, "process": 0.25, "delivery": 0.15},
  "sga_spend": 12000000,
  "equity_issuance_request": 0,
  "debt_request": 0,
  "dividends": 0,
  "buybacks": 0,
  "reasoning": "Maintaining current strategy while building R&D pipeline."
}
```'''
