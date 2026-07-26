#!/usr/bin/env python3
"""Download Qwen 2.5-VL 72B AWQ model weights from HuggingFace.

Pure file download via huggingface_hub.snapshot_download — deliberately
does not import torch/transformers or instantiate the model. Downloading
should not require a working inference stack (and must not try to load
a 72B model into memory just to fetch its files).

Also patches a real bug in the checkpoint's own config.json: its
quantization_config.modules_to_not_convert lists "visual" (meant to keep
the vision tower unquantized), but transformers' should_convert_module()
only matches skip patterns against a path prefix or suffix of the actual
dotted module name (e.g. "model.visual.blocks.0.attn.proj"), never a bare
substring. "visual" alone never matches, so the loader silently tries to
quantize the vision tower, fails to find quantized weights for it in the
checkpoint, and falls back to randomly-initialized vision weights instead
of erroring. Fixed by listing the actual prefix.
"""

import json
import sys
from pathlib import Path

MODEL_REPO = "Qwen/Qwen2.5-VL-72B-Instruct-AWQ"
MODEL_NAME = "Qwen2.5-VL-72B-Instruct-AWQ"


def _fix_quantization_config(model_path: Path) -> None:
    config_path = model_path / "config.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    quant_cfg = cfg.get("quantization_config")
    if not quant_cfg:
        return
    skips = set(quant_cfg.get("modules_to_not_convert") or [])
    skips.update({"visual", "model.visual"})
    quant_cfg["modules_to_not_convert"] = sorted(skips)
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Patched modules_to_not_convert in {config_path} -> {quant_cfg['modules_to_not_convert']}")


def download_model() -> bool:
    from huggingface_hub import snapshot_download

    models_dir = Path(__file__).parent / "models"
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / MODEL_NAME

    print(f"Downloading {MODEL_REPO} to {model_path} ...")
    print("This is ~43GB and can take a while depending on bandwidth.")

    try:
        snapshot_download(
            repo_id=MODEL_REPO,
            local_dir=str(model_path),
            max_workers=4,
        )
        _fix_quantization_config(model_path)
    except Exception as exc:
        print(f"Error downloading model: {exc}")
        import traceback

        traceback.print_exc()
        return False

    print(f"Model ready at {model_path}")
    return True


if __name__ == "__main__":
    sys.exit(0 if download_model() else 1)
