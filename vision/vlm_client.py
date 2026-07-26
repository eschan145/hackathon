"""Thin client for a local vision-language model exposed over an
OpenAI-compatible multimodal chat endpoint (NVIDIA NIM style).

Used both by Verification (success-detection judge, ARCHITECTURE.md
section 7 step 1/4) and by Execution/vision element_detection.py for
UI grounding ("Set-of-Marks"-style prompting over an already-annotated
image with numbered candidate boxes, section 9).

Mirrors the config pattern in config/models.yaml (planning.base_url /
model / api_key / timeout) but for a `vision` profile — falls back to
env vars, then hardcoded localhost defaults, matching planning/llm_client.py's
approach so both subsystems degrade the same way when the config file is
missing a section.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from PIL import Image
from pydantic import BaseModel, Field, ValidationError

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover - optional, but lightweight
    httpx = None  # TODO: `pip install httpx`. Needed for the actual NIM
    # HTTP call; without it LocalVLMClient.ask returns a stubbed low-confidence
    # response so callers can still exercise their control flow.

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # TODO: `pip install pyyaml` to read config/models.yaml.
    # Falls back to env vars / hardcoded defaults if unavailable.


class VLMAnswer(BaseModel):
    """Structured output contract for LocalVLMClient.ask.

    `answer` is `bool` for yes/no verification questions ("does this
    screenshot satisfy X?") or `str`/int-as-str for grounding questions
    ("which numbered box is the Submit button?") — kept as `Any` at the
    wire level and normalized by callers, since the same endpoint serves
    both use cases per ARCHITECTURE.md section 9.
    """

    answer: Any
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


@dataclass
class VLMConfig:
    base_url: str = "http://localhost:8001/v1"
    model: str = "nvidia/neva-22b"  # placeholder NIM VLM model id
    api_key: str = "not-needed"
    timeout_seconds: float = 60.0


def _load_vlm_config(config_path: Optional[str] = None) -> VLMConfig:
    path = config_path or str(
        (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + os.sep + "config" + os.sep + "models.yaml"
    )
    cfg = VLMConfig()
    data: dict[str, Any] = {}
    if yaml is not None and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                parsed = yaml.safe_load(f) or {}
            data = parsed.get("vision", {}) or {}
        except Exception:
            data = {}
    return VLMConfig(
        base_url=os.environ.get("HACKATHON_VLM_BASE_URL", data.get("base_url", cfg.base_url)),
        model=os.environ.get("HACKATHON_VLM_MODEL", data.get("model", cfg.model)),
        api_key=os.environ.get("HACKATHON_VLM_API_KEY", data.get("api_key", cfg.api_key)),
        timeout_seconds=float(data.get("timeout_seconds", cfg.timeout_seconds)),
    )


def _image_to_data_uri(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


_JSON_SCHEMA_INSTRUCTION = (
    "Respond with ONLY a JSON object matching this schema, no prose outside it:\n"
    '{"answer": <bool or string>, "confidence": <float 0-1>, "reasoning": <string>}'
)


class LocalVLMClient:
    """Wraps a local OpenAI-compatible multimodal chat endpoint.

    `ask(image, question)` covers both:
      - verification: question is a yes/no success-criteria check, answer
        should be interpreted as bool.
      - execution-time grounding (Set-of-Marks): `image` can already be
        annotated with numbered candidate boxes, and `question` asks the
        model to pick one by number; answer is then the chosen label/id
        as a string.
    """

    def __init__(self, config: Optional[VLMConfig] = None) -> None:
        self.config = config or _load_vlm_config()

    async def ask(self, image: Image.Image, question: str) -> dict[str, Any]:
        """Returns {"answer": bool|str, "confidence": float, "reasoning": str}.

        On any transport/parsing failure, degrades to a low-confidence
        "unknown" answer rather than raising, so callers (verifier,
        element_detection) can treat it as "inconclusive" and fall back to
        another check rather than crash the pipeline.
        """
        if httpx is None:
            return {
                "answer": False,
                "confidence": 0.0,
                "reasoning": "httpx not installed; VLM call skipped (stub response).",
            }

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{question}\n\n{_JSON_SCHEMA_INSTRUCTION}"},
                        {"type": "image_url", "image_url": {"url": _image_to_data_uri(image)}},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                resp = await client.post(
                    f"{self.config.base_url}/chat/completions", json=payload, headers=headers
                )
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                validated = VLMAnswer.model_validate(parsed)
                return validated.model_dump()
        except (httpx.HTTPError, json.JSONDecodeError, ValidationError, KeyError, IndexError) as exc:
            return {
                "answer": False,
                "confidence": 0.0,
                "reasoning": f"VLM call failed/unparsable: {exc!r}",
            }


default_vlm_client = LocalVLMClient()
