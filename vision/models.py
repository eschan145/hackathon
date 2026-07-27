"""Shared lightweight data shapes for the vision subsystem.

Split out from screen_state.py/windows.py/apps.py so those three modules
can import each other's return types without a circular import (screen_state
composes windows+apps+ocr, windows/apps only need the plain data shapes).
"""

from __future__ import annotations

from typing import Optional, Tuple

from pydantic import BaseModel


class Element(BaseModel):
    """One OCR-detected text element on screen — a click/type target."""

    id: int
    text: str
    bbox: Tuple[int, int, int, int]  # (left, top, right, bottom), screen pixels


class WindowInfo(BaseModel):
    """One open window, per `wmctrl -lx` / `xdotool`."""

    id: str  # wmctrl/xdotool window id, e.g. "0x02c00003"
    app: str  # WM_CLASS-derived application name
    title: str
    active: bool = False
    desktop: Optional[int] = None


class InstalledApp(BaseModel):
    """One parsed `.desktop` entry."""

    name: str
    exec_cmd: str
    desktop_id: str  # filename stem, e.g. "org.gnome.Nautilus"
