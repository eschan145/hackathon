#!/usr/bin/env python3
"""OpenAI-compatible server for the local Qwen2.5-VL model.

This is the only model backend for the project (see config/models.yaml
and planning/openclaw_client.py's LOCAL_MODEL_ID guard) — no cloud model
is ever an acceptable substitute. OpenClaw talks to this server as a
custom OpenAI-compatible provider over /v1/chat/completions.
"""

import time
import uuid
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()

MODELS_DIR = Path(__file__).parent / "models"
MODEL_NAME = "Qwen2.5-VL-72B-Instruct-AWQ"
MODEL_PATH = MODELS_DIR / MODEL_NAME
MODEL_REPO = "Qwen/Qwen2.5-VL-72B-Instruct-AWQ"

MODEL_ID = "qwen-2.5-vl-72b-local"

_model = None
_processor = None
_device = None


def load_model() -> bool:
    """Load the Qwen2.5-VL model + processor."""
    global _model, _processor, _device

    try:
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {_device}")

        model_repo = str(MODEL_PATH) if MODEL_PATH.exists() else MODEL_REPO
        print(f"Loading model from {model_repo}...")

        _processor = AutoProcessor.from_pretrained(model_repo)
        print("Processor loaded")

        # NOTE: download_model.py patches the checkpoint's own config.json to
        # fix modules_to_not_convert (["visual"] -> also includes
        # "model.visual", the actual dotted module prefix) so the AWQ
        # quantizer correctly leaves the vision tower unquantized instead of
        # silently falling back to randomly-initialized vision weights. If
        # you re-download the model without that patch, loading will
        # "succeed" with a broken (untrained) vision encoder — see the
        # missing/mismatched-keys check below, which turns that into a loud
        # failure instead.
        _model, loading_info = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_repo,
            device_map="auto",
            torch_dtype=torch.float16 if _device == "cuda" else torch.float32,
            output_loading_info=True,
        )
        _model.eval()

        bad_visual_keys = [
            k
            for k in loading_info.get("missing_keys", []) + loading_info.get("mismatched_keys", [])
            if "visual" in k
        ]
        if bad_visual_keys:
            raise RuntimeError(
                f"Vision tower failed to load from checkpoint ({len(bad_visual_keys)} "
                f"keys missing/mismatched, e.g. {bad_visual_keys[0]!r}); refusing to "
                f"serve a model with a randomly-initialized vision encoder. Check "
                f"{model_repo}/config.json's quantization_config.modules_to_not_convert."
            )
        print("Model loaded successfully")

        return True

    except ImportError as e:
        print(f"Missing dependencies: {e}")
        print("Install with: pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"Error loading model: {e}")
        import traceback

        traceback.print_exc()
        return False


def _content_to_parts(content) -> list[dict]:
    """Normalize an OpenAI-style message `content` field to Qwen chat-template parts.

    `content` is either a plain string, or a list of
    {"type": "text", "text": ...} / {"type": "image_url", "image_url": {"url": ...}}
    parts (the shape OpenClaw sends for text+image requests).
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    parts: list[dict] = []
    for item in content or []:
        item_type = item.get("type")
        if item_type == "text":
            parts.append({"type": "text", "text": item.get("text", "")})
        elif item_type == "image_url":
            url = (item.get("image_url") or {}).get("url", "")
            parts.append({"type": "image", "image": url})
    return parts


def _run_generation(messages: list[dict], max_tokens: int, temperature: float) -> tuple[str, int, int]:
    from qwen_vl_utils import process_vision_info

    if _model is None or _processor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    chat = [{"role": m.get("role", "user"), "content": _content_to_parts(m.get("content", ""))} for m in messages]

    text = _processor.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(chat)

    inputs = _processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(_model.device)

    with torch.no_grad():
        generated_ids = _model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            temperature=temperature if temperature > 0 else None,
            do_sample=temperature > 0,
        )

    prompt_len = inputs.input_ids.shape[1]
    trimmed = generated_ids[:, prompt_len:]
    response_text = _processor.batch_decode(
        trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0]

    return response_text, prompt_len, trimmed.shape[1]


@app.get("/v1/models")
async def list_models():
    return {
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "owned_by": "local",
                "permission": [{"allow": "allow"}],
            }
        ],
        "object": "list",
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    max_tokens = data.get("max_tokens", 512)
    temperature = data.get("temperature", 0.7)

    try:
        response_text, prompt_tokens, completion_tokens = _run_generation(
            messages, max_tokens, temperature
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error during inference: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "id": f"local-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@app.get("/health")
async def health():
    return {
        "status": "ready" if _model is not None else "loading",
        "model": MODEL_ID,
        "device": str(_device),
        "model_loaded": _model is not None,
    }


if __name__ == "__main__":
    print(f"Loading {MODEL_NAME}...")
    print(f"Model path: {MODEL_PATH}")

    if not load_model():
        print("WARNING: Running in degraded mode - model failed to load")

    print("Starting OpenAI-compatible server on http://0.0.0.0:8766")
    print(f"Using model: {MODEL_ID}")
    print(f"Device: {_device}")

    uvicorn.run(app, host="0.0.0.0", port=8766, log_level="info")
