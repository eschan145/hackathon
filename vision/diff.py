"""Simple perceptual frame diffing to detect UI "settle" before capturing
the post-action verification frame (ARCHITECTURE.md section 6/9: "frames
diffed to detect UI settle before verifying").
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def frames_changed(img_a: Image.Image, img_b: Image.Image, threshold: float = 0.02) -> bool:
    """Returns True if the fraction of meaningfully-changed pixels between
    `img_a` and `img_b` exceeds `threshold` (default 2%).

    Images are resized to match if dimensions differ (e.g. window resize
    mid-task) and converted to grayscale before diffing to keep this cheap
    — this is a coarse "did anything change" signal, not a semantic diff.
    """
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size)

    a = np.asarray(img_a.convert("L"), dtype=np.int16)
    b = np.asarray(img_b.convert("L"), dtype=np.int16)

    delta = np.abs(a - b)
    changed_pixels = np.count_nonzero(delta > 10)  # per-pixel intensity tolerance
    ratio = changed_pixels / delta.size
    return ratio > threshold


async def wait_for_settle(
    capture_fn,
    *,
    poll_interval: float = 0.3,
    max_polls: int = 10,
    threshold: float = 0.02,
) -> "Image.Image":
    """Polls `capture_fn()` (sync callable returning a PIL Image) until two
    consecutive frames are unchanged (UI has "settled"), or `max_polls` is
    reached. Returns the last captured frame either way.

    Kept async (with a plain asyncio.sleep) since this is meant to be
    awaited from the async Verifier.verify() / Executor.execute() paths
    without blocking the event loop.
    """
    import asyncio

    prev = capture_fn()
    for _ in range(max_polls):
        await asyncio.sleep(poll_interval)
        curr = capture_fn()
        if not frames_changed(prev, curr, threshold=threshold):
            return curr
        prev = curr
    return prev
