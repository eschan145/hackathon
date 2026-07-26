"""Linux-native window enumeration/focus/geometry, via `wmctrl` + `xdotool`.

Replaces the old Windows-only pywinauto/pygetwindow window layer. Every
function here shells out to a small system tool and degrades gracefully
(returns `[]`/`None`/`False`) if the tool isn't installed, times out, or
fails — matching the rest of the vision subsystem's "never crash the
pipeline" style (see vision/capture.py's soft-imports).
"""

from __future__ import annotations

import subprocess
from typing import Optional

from vision.models import WindowInfo

_SUBPROCESS_TIMEOUT = 5


def _run(args: list[str]) -> Optional[str]:
    """Run a command, returning stdout on success or None on any failure."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _app_name_from_wm_class(wm_class: str) -> str:
    """`wmctrl -lx`'s WM_CLASS column looks like "app.class" (e.g.
    "firefox.Firefox") — take the part after the last dot, or the whole
    thing if there's no dot.
    """
    if "." in wm_class:
        return wm_class.rsplit(".", 1)[-1]
    return wm_class


def list_open_windows() -> list[WindowInfo]:
    """Enumerate open windows via `wmctrl -lx`.

    Each output line looks like:
        0x02c00003  0 firefox.Firefox   hostname  Mozilla Firefox
    (id, desktop, WM_CLASS, host, title...) — title may contain spaces so
    we cap the split.
    """
    stdout = _run(["wmctrl", "-lx"])
    if stdout is None:
        return []

    windows: list[WindowInfo] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        win_id, desktop_str, wm_class = parts[0], parts[1], parts[2]
        title = parts[4] if len(parts) >= 5 else ""

        try:
            desktop: Optional[int] = int(desktop_str)
        except ValueError:
            desktop = None

        windows.append(
            WindowInfo(
                id=win_id,
                app=_app_name_from_wm_class(wm_class),
                title=title,
                active=False,
                desktop=desktop,
            )
        )
    return windows


def get_active_window_id() -> Optional[str]:
    """The currently focused window's id, via `xdotool getactivewindow`."""
    stdout = _run(["xdotool", "getactivewindow"])
    if stdout is None:
        return None
    win_id = stdout.strip()
    if not win_id:
        return None
    # xdotool prints a decimal window id; wmctrl -lx prints the same X11
    # window id as zero-padded 8-digit hex (e.g. "0x03a091a8"). Plain
    # `hex(int(win_id))` drops leading zero nibbles (giving "0x3a091a8"),
    # which silently fails the string-equality check ScreenState uses to
    # mark a window active against list_open_windows()'s ids — pad to
    # match wmctrl's width so the two are actually comparable.
    try:
        return f"0x{int(win_id):08x}"
    except ValueError:
        return win_id


def focus_window(window_id: str) -> bool:
    """Activate the given window id via `xdotool windowactivate`."""
    stdout = _run(["xdotool", "windowactivate", window_id])
    return stdout is not None


def get_window_geometry(window_id: Optional[str] = None) -> Optional[tuple[int, int, int, int]]:
    """Return (left, top, width, height) in screen pixels for a window.

    `window_id=None` means "the active window". Uses
    `xdotool getwindowgeometry --shell <id>`, which prints lines like:
        WINDOW=12345
        X=100
        Y=200
        WIDTH=800
        HEIGHT=600
        SCREEN=0
    """
    target = window_id
    if target is None:
        stdout = _run(["xdotool", "getactivewindow"])
        if stdout is None:
            return None
        target = stdout.strip()
        if not target:
            return None

    stdout = _run(["xdotool", "getwindowgeometry", "--shell", target])
    if stdout is None:
        return None

    values: dict[str, int] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        try:
            values[key.strip()] = int(raw_value.strip())
        except ValueError:
            continue

    try:
        return (values["X"], values["Y"], values["WIDTH"], values["HEIGHT"])
    except KeyError:
        return None
