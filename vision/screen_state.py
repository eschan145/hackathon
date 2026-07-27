"""The vision engine's single entry point: capture_screen_state().

Produces a `ScreenState` — screenshot + numbered OCR text elements + open
windows + (optionally) installed apps — and a compact `.to_prompt_text()`
serialization. This is the "efficient format" handed to
planning/vision_agent_planner.py each turn; it is deliberately algorithmic
(OCR + window/app enumeration, no model call) so most turns cost zero extra
inference — the OpenClaw model is only ever consulted to *decide actions*,
never to describe the screen.

Element/window ids are only valid for the ScreenState they came from —
they are reassigned every capture, by design (see planning/action_dsl.py's
docstring), so the interpreter always resolves ids against the same
ScreenState instance the planner reasoned about.
"""

from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field

from vision.apps import list_installed_apps
from vision.capture import capture_screen, default_frame_store
from vision.models import Element, InstalledApp, WindowInfo
from vision.ocr import default_ocr_engine
from vision.windows import get_active_window_id, list_open_windows

# OCR boxes shorter than this are almost always noise (stray punctuation,
# partial glyphs) rather than a usable click/type target.
_MIN_ELEMENT_TEXT_LEN = 1
# Screenshots are large; keep the prompt-text element list bounded so a
# busy/cluttered screen doesn't blow up token usage on its own.
_MAX_ELEMENTS_IN_PROMPT = 120


class ScreenState(BaseModel):
    """One vision-engine capture: everything the planner needs to decide the next action."""

    elements: list[Element] = Field(default_factory=list)
    windows: list[WindowInfo] = Field(default_factory=list)
    active_window_id: Optional[str] = None
    installed_apps: list[InstalledApp] = Field(default_factory=list)
    screenshot_ref: Optional[str] = None
    captured_at: float = Field(default_factory=time.time)

    def element_by_id(self, element_id: int) -> Optional[Element]:
        for el in self.elements:
            if el.id == element_id:
                return el
        return None

    def window_by_id(self, window_id: str) -> Optional[WindowInfo]:
        for win in self.windows:
            if win.id == window_id:
                return win
        return None

    def to_prompt_text(self) -> str:
        """Compact, token-efficient text serialization for the model prompt."""
        lines: list[str] = []

        active = self.window_by_id(self.active_window_id) if self.active_window_id else None
        if active is not None:
            lines.append(f"ACTIVE WINDOW: [{active.id}] {active.app} - {active.title}")
        else:
            lines.append("ACTIVE WINDOW: (none detected)")

        if self.windows:
            lines.append("OPEN WINDOWS:")
            for win in self.windows:
                marker = " (active)" if win.active else ""
                lines.append(f"  [{win.id}] {win.app} - {win.title}{marker}")
        else:
            lines.append("OPEN WINDOWS: (none)")

        shown = self.elements[:_MAX_ELEMENTS_IN_PROMPT]
        if shown:
            lines.append("TEXT ELEMENTS (id: \"text\" @ left,top,right,bottom):")
            for el in shown:
                l, t, r, b = el.bbox
                lines.append(f"  {el.id}: \"{el.text}\" @ {l},{t},{r},{b}")
            if len(self.elements) > len(shown):
                lines.append(f"  ...({len(self.elements) - len(shown)} more elements omitted)")
        else:
            lines.append("TEXT ELEMENTS: (none detected)")

        if self.installed_apps:
            names = ", ".join(app.name for app in self.installed_apps)
            lines.append(f"INSTALLED APPS: {names}")

        return "\n".join(lines)


def capture_screen_state(*, include_installed_apps: bool = False) -> ScreenState:
    """Capture one algorithmic snapshot of the current screen/desktop state.

    `include_installed_apps` should only be True on the first turn of a
    task (or when the planner explicitly needs it, e.g. a `launch(...)`
    failed because the app name didn't match anything) — the list is
    cached (see vision/apps.py) so repeated calls are cheap, but it's still
    unnecessary weight in every single turn's prompt.
    """
    image = capture_screen()
    screenshot_ref = default_frame_store.save(image)

    boxes = default_ocr_engine.extract_text_boxes(image)
    elements = [
        Element(
            id=i + 1,
            text=box["text"].strip(),
            bbox=tuple(int(v) for v in box["bbox"]),  # type: ignore[arg-type]
        )
        for i, box in enumerate(boxes)
        if len(box["text"].strip()) >= _MIN_ELEMENT_TEXT_LEN
    ]

    windows = list_open_windows()
    active_id = get_active_window_id()
    for win in windows:
        win.active = win.id == active_id

    installed_apps = list_installed_apps() if include_installed_apps else []

    return ScreenState(
        elements=elements,
        windows=windows,
        active_window_id=active_id,
        installed_apps=installed_apps,
        screenshot_ref=screenshot_ref,
    )
