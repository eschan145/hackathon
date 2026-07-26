"""Screen capture + ring-buffer frame store.

Per ARCHITECTURE.md section 9 (Vision Subsystem): `mss` is used for
cross-platform screen capture (DXGI duplication would be a Windows-only
lower-overhead alternative, not implemented here for hackathon scope).
Frames are cached in a small ring-buffer directory so Verification can diff
against pre-action state without re-capturing (section 9, "shared cache").
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

try:
    import mss  # type: ignore
except ImportError:  # pragma: no cover - optional heavy dep
    mss = None  # TODO: `pip install mss` for real screen capture; without it
    # capture_screen falls back to a blank placeholder image so the rest of
    # the pipeline (OCR/VLM/diff) can still be exercised in dev/CI.

from vision.windows import get_window_geometry

Region = tuple[int, int, int, int]  # (left, top, width, height)


def capture_screen(region: Optional[Region] = None) -> Image.Image:
    """Capture the full screen (or a region) as a PIL Image.

    `region` is (left, top, width, height) in screen pixel coordinates.
    Uses `mss` under the hood; if `mss` isn't installed, returns a blank
    placeholder image of the requested (or a default 1920x1080) size so
    downstream code doesn't crash in environments without display access.
    """
    if mss is None:
        w, h = (region[2], region[3]) if region else (1920, 1080)
        return Image.new("RGB", (w, h), color=(32, 32, 32))

    with mss.mss() as sct:
        if region is not None:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = sct.monitors[0]  # full virtual screen across all monitors
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _active_window_region() -> Optional[Region]:
    """Best-effort active-window bounding box, or None if unavailable.

    Delegates to vision.windows.get_window_geometry() (wmctrl/xdotool
    under the hood), which already degrades to None if those tools aren't
    on PATH or the call fails for any reason.
    """
    return get_window_geometry()


def capture_active_window() -> Image.Image:
    """Capture just the active window; falls back to full-screen capture
    if window bounds can't be determined (no gui lib installed, headless
    environment, or unsupported platform).
    """
    region = _active_window_region()
    return capture_screen(region)


_IMPORT_TIMEOUT = 10


def capture_window(window_id: str) -> Optional[Image.Image]:
    """Capture one window's contents via `import -window <id>`, reading its
    composited off-screen pixmap so occluded windows capture correctly
    without being raised/focused. Accepts WindowInfo.id as-is (decimal or
    0x-hex both work). Returns None on failure; note a bad window id makes
    `import` exit 0 and silently fall back to the focused window, reporting
    the real error only on stderr — so any stderr output counts as failure.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        try:
            result = subprocess.run(
                ["import", "-window", window_id, tmp_path],
                capture_output=True,
                timeout=_IMPORT_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or result.stderr.strip():
            return None
        try:
            with Image.open(tmp_path) as img:
                return img.copy()
        except (UnidentifiedImageError, OSError):
            return None
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


class FrameStore:
    """Ring buffer of recently captured frames, persisted to a scratch dir.

    Verification/execution code calls `save()` right after a capture and
    gets back an opaque `ref_id` (this is what populates
    `ActionResult.screenshot_ref`); later, `get()` reloads the image by
    that id. Only the last `max_frames` images are kept on disk.
    """

    def __init__(self, directory: Optional[str | Path] = None, max_frames: int = 50) -> None:
        self.directory = Path(
            directory or os.environ.get("HACKATHON_FRAME_DIR")
            or (Path(__file__).resolve().parent.parent / "data" / "frames")
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_frames = max_frames

    def save(self, image: Image.Image) -> str:
        ref_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        path = self._path_for(ref_id)
        image.save(path, format="PNG")
        self._evict_old()
        return ref_id

    def get(self, ref_id: str) -> Image.Image:
        path = self._path_for(ref_id)
        if not path.exists():
            raise FileNotFoundError(f"No frame with ref_id={ref_id!r} in {self.directory}")
        return Image.open(path)

    def _path_for(self, ref_id: str) -> Path:
        return self.directory / f"{ref_id}.png"

    def _evict_old(self) -> None:
        frames = sorted(self.directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
        excess = len(frames) - self.max_frames
        for old in frames[:max(excess, 0)]:
            try:
                old.unlink()
            except OSError:
                pass


# Module-level default store so callers across vision/ and verification/
# can share the same ring buffer without threading an instance through.
default_frame_store = FrameStore()
