"""Thin async client for a local OpenAI-compatible chat-completions endpoint.

Targets whatever is running on the DGX Spark box behind an OpenAI-compatible
HTTP API — NVIDIA NIM, vLLM's `--served-model` OpenAI server, or Ollama's
`/v1/chat/completions` shim all satisfy this. No cloud calls are ever made;
`base_url` should always point at localhost/the local network.

Config is read from `config/models.yaml` (planning.* keys) with env var
overrides and hardcoded fallbacks — intentionally minimal, no schema
validation layer, per the hackathon-scope note in ARCHITECTURE.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Type, TypeVar

import httpx
import yaml
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"

_DEFAULTS = {
    "base_url": "http://localhost:8000/v1",
    "model": "meta/llama-3.1-70b-instruct",
    "api_key": "not-needed",
    "temperature": 0.2,
    "max_tokens": 4096,
    "timeout_seconds": 120,
}


def _load_config(section: str = "planning") -> dict[str, Any]:
    """Read config/models.yaml, falling back to env vars then defaults.

    Deliberately simple: one file, one section, no merging logic beyond
    "yaml value if present, else env var, else default".
    """
    cfg: dict[str, Any] = dict(_DEFAULTS)
    try:
        if _CONFIG_PATH.exists():
            raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
            section_cfg = raw.get(section, {}) if isinstance(raw, dict) else {}
            if isinstance(section_cfg, dict):
                cfg.update({k: v for k, v in section_cfg.items() if v is not None})
    except Exception:
        # Config is best-effort for a hackathon build; fall back silently.
        pass

    env_prefix = f"LOCAL_LLM_{section.upper()}_"
    for key in list(cfg.keys()):
        env_val = os.environ.get(f"{env_prefix}{key.upper()}") or os.environ.get(
            f"LOCAL_LLM_{key.upper()}"
        )
        if env_val is not None:
            cfg[key] = env_val
    return cfg


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from an LLM response.

    Handles the common case of a clean JSON body, but also strips markdown
    code fences and grabs the outermost {...} block if the model chattered
    around the JSON despite instructions not to.
    """
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"Could not locate a JSON object in LLM response: {text[:200]!r}")


class LocalLLMClient:
    """Async wrapper around a local OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        config_section: str = "planning",
    ) -> None:
        cfg = _load_config(config_section)
        self.base_url: str = (base_url or cfg["base_url"]).rstrip("/")
        self.model: str = model or cfg["model"]
        self.api_key: str = api_key or cfg["api_key"]
        self.temperature: float = float(temperature if temperature is not None else cfg["temperature"])
        self.max_tokens: int = int(max_tokens if max_tokens is not None else cfg["max_tokens"])
        self.timeout_seconds: float = float(
            timeout_seconds if timeout_seconds is not None else cfg["timeout_seconds"]
        )

    async def _chat(self, system_prompt: str, user_prompt: str, *, json_mode: bool = True) -> str:
        """POST a single chat-completion request; returns the assistant message text."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            # OpenAI-compatible servers (vLLM, NIM, recent Ollama) generally
            # support this; harmless no-op if the backend ignores it.
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[ModelT],
    ) -> ModelT:
        """Ask the LLM for JSON matching `response_model` and validate it.

        Retries once (with the parse/validation error fed back to the model)
        if the first response fails to parse or validate.
        """
        last_error: Exception | None = None
        current_user_prompt = user_prompt

        for attempt in range(2):
            try:
                raw_text = await self._chat(system_prompt, current_user_prompt)
                obj = _extract_json(raw_text)
                return response_model.model_validate(obj)
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                last_error = exc
                current_user_prompt = (
                    f"{user_prompt}\n\n"
                    "Your previous response could not be parsed/validated as the required "
                    f"JSON schema. Error: {exc}\n"
                    "Return ONLY a single valid JSON object matching the schema, with no "
                    "prose or markdown fences."
                )
                continue

        assert last_error is not None
        raise RuntimeError(
            f"LLM failed to produce valid {response_model.__name__} JSON after retry: {last_error}"
        )
