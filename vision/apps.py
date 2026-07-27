"""Linux-native installed-app enumeration + launch, via freedesktop
.desktop files.

This is the one deliberate cache in the vision layer: installed apps
rarely change between turns (or even between runs), so we cache the
parsed list to data/installed_apps_cache.json and only rescan when the
cache is stale or a source directory has changed. Contrast with
screen_state.py, which must never be cached — the whole point there is a
fresh read every turn.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional

from execution.audit_log import log_action
from vision.models import InstalledApp

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _REPO_ROOT / "data" / "installed_apps_cache.json"
_APP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
]
# Freedesktop Exec= field codes (%f/%F/%u/%U/%d/%D/%n/%N/%i/%c/%k/%v/%m) are
# for file/URL/icon/etc args we're not passing — strip them out.
_FIELD_CODE_RE = re.compile(r"%[fFuUdDnNickvm]")


def _strip_field_codes(exec_value: str) -> str:
    return _FIELD_CODE_RE.sub("", exec_value).strip()


def _parse_desktop_file(path: Path) -> Optional[InstalledApp]:
    """Manually parse the [Desktop Entry] section of a .desktop file.

    Freedesktop .desktop files are ini-like but have quirks (duplicate
    keys, extra [Desktop Action ...] sections, comments starting with
    '#', no value quoting) that trip up configparser's strict mode — so
    we parse just the section we care about by hand rather than fight it.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    in_target_section = False
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_target_section = line == "[Desktop Entry]"
            continue
        if not in_target_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # First occurrence of a key in the section wins (top-of-file rule).
        fields.setdefault(key, value.strip())

    if fields.get("Type", "Application") != "Application":
        return None
    if fields.get("NoDisplay", "false").lower() == "true":
        return None
    if fields.get("Hidden", "false").lower() == "true":
        return None

    name = fields.get("Name")
    exec_raw = fields.get("Exec")
    if not name or not exec_raw:
        return None

    exec_cmd = _strip_field_codes(exec_raw)
    if not exec_cmd:
        return None

    return InstalledApp(name=name, exec_cmd=exec_cmd, desktop_id=path.stem)


def _source_dirs_mtime() -> float:
    """Newest mtime across all app source directories that exist, or 0.0."""
    newest = 0.0
    for directory in _APP_DIRS:
        try:
            newest = max(newest, directory.stat().st_mtime)
        except OSError:
            continue
    return newest


def _load_cache() -> Optional[dict]:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_cache(apps: list[InstalledApp]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cached_at": time.time(),
            "apps": [app.model_dump() for app in apps],
        }
        _CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # cache is a pure optimization; failing to write it is fine


def _scan_desktop_files() -> list[InstalledApp]:
    seen_ids: set[str] = set()
    apps: list[InstalledApp] = []
    for directory in _APP_DIRS:
        if not directory.is_dir():
            continue
        for entry in sorted(directory.glob("*.desktop")):
            app = _parse_desktop_file(entry)
            if app is None or app.desktop_id in seen_ids:
                continue
            seen_ids.add(app.desktop_id)
            apps.append(app)
    return apps


def list_installed_apps(cache_ttl: float = 3600.0) -> list[InstalledApp]:
    """List installed GUI applications, parsed from .desktop files.

    Cached to data/installed_apps_cache.json; recomputed if the cache is
    older than `cache_ttl` seconds OR any source directory's mtime is
    newer than the cache's timestamp (an app was installed/removed since).
    """
    cache = _load_cache()
    if cache is not None:
        cached_at = cache.get("cached_at", 0.0)
        age = time.time() - cached_at
        if age <= cache_ttl and _source_dirs_mtime() <= cached_at:
            try:
                return [InstalledApp(**raw) for raw in cache["apps"]]
            except (KeyError, TypeError, ValueError):
                pass  # malformed cache: fall through to a fresh scan

    apps = _scan_desktop_files()
    _save_cache(apps)
    return apps


def find_app_by_name(name: str, apps: Optional[list[InstalledApp]] = None) -> Optional[InstalledApp]:
    """Fuzzy, case-insensitive match against InstalledApp.name.

    The model names apps loosely ("GNOME Calculator", "the Text Editor
    app") which often isn't a plain substring of the .desktop entry's
    actual Name= in either direction (e.g. GNOME's calculator app is
    simply named "Calculator"). Three passes, most exact first:
      1. exact match (case-insensitive)
      2. substring match, either direction
      3. token overlap (ignoring filler words like "app"/"application")
    """
    candidates = apps if apps is not None else list_installed_apps()
    needle = name.strip().lower()
    if not needle:
        return None

    for app in candidates:
        if needle == app.name.lower():
            return app

    for app in candidates:
        app_lower = app.name.lower()
        if needle in app_lower or app_lower in needle:
            return app

    filler = {"the", "app", "application", "program", "gnome", "utility"}
    needle_tokens = {t for t in re.split(r"\W+", needle) if t and t not in filler}
    if needle_tokens:
        for app in candidates:
            app_tokens = {t for t in re.split(r"\W+", app.name.lower()) if t and t not in filler}
            if needle_tokens & app_tokens:
                return app

    return None


def launch_app(name: str) -> bool:
    """Launch an installed app by (fuzzy) name.

    Resolves via find_app_by_name() and runs its Exec command directly,
    returning True as soon as the process is spawned (best-effort — GUI
    apps don't exit, so we never wait on them). Falls back to
    `gtk-launch <name>` if no .desktop match was found (or the resolved
    Exec command couldn't be spawned).
    """
    app = find_app_by_name(name)
    if app is not None:
        try:
            args = shlex.split(app.exec_cmd)
        except ValueError:
            args = []
        if args:
            try:
                subprocess.Popen(
                    args,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log_action(
                    "launch_app",
                    {
                        "backend": "native",
                        "app_name": name,
                        "resolved": app.name,
                        "exec_cmd": app.exec_cmd,
                        "success": True,
                    },
                )
                return True
            except OSError:
                pass  # fall through to the gtk-launch fallback below

    try:
        proc = subprocess.Popen(
            ["gtk-launch", name],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log_action(
            "launch_app",
            {"backend": "native", "app_name": name, "resolved": None, "success": False},
        )
        return False

    # Best-effort: give the process a brief moment to fail fast (e.g.
    # "No such desktop file") before reporting success — not a robust
    # wait, just enough to catch the immediate-failure case.
    time.sleep(0.1)
    if proc.poll() is not None and proc.returncode != 0:
        log_action(
            "launch_app",
            {"backend": "native", "app_name": name, "resolved": None, "via": "gtk-launch", "success": False},
        )
        return False

    log_action(
        "launch_app",
        {"backend": "native", "app_name": name, "resolved": None, "via": "gtk-launch", "success": True},
    )
    return True
