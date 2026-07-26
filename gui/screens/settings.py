"""SettingsScreen: backend selection, allow-listed directories, model selection.

ARCHITECTURE.md section 10 ("SettingsScreen (backend selection,
allow-listed apps/dirs, model selection)") and section 6 (ControlBackend
choices: OpenClaw/NemoClaw/Native) and section 12 (allow-listed dirs feed
`config/security_policy.yaml` in the real FileOps module — this screen
just persists user-facing preferences to a simple yaml for the demo;
wiring it into the live security policy is a follow-up integration task).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

try:
    import yaml
    _YAML_AVAILABLE = True
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "user_settings.yaml"

BACKEND_CHOICES = ["Native", "OpenClaw", "NemoClaw"]

DEFAULT_SETTINGS: dict[str, Any] = {
    "backend": "Native",
    "planning_model": "llama-3.1-70b-instruct",
    "verification_model": "nemotron-vision-small",
    "allowed_directories": [
        str(Path.home() / "Documents"),
        str(Path.home() / "Downloads"),
    ],
}


class SettingsScreen(Screen):
    """Persists demo settings (backend/model/allow-listed dirs) to yaml."""

    def on_pre_enter(self, *args) -> None:
        self._settings = self._load_settings()
        self._populate_widgets()

    # -- persistence -----------------------------------------------------

    def _load_settings(self) -> dict[str, Any]:
        if _YAML_AVAILABLE and SETTINGS_PATH.exists():
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                merged = dict(DEFAULT_SETTINGS)
                merged.update(data)
                return merged
            except Exception:
                logger.exception("Failed to read %s, using defaults", SETTINGS_PATH)
        return dict(DEFAULT_SETTINGS)

    def save_settings(self) -> None:
        backend_spinner = self.ids.get("backend_spinner")
        planning_model_input = self.ids.get("planning_model_input")
        verification_model_input = self.ids.get("verification_model_input")

        if backend_spinner is not None:
            self._settings["backend"] = backend_spinner.text
        if planning_model_input is not None:
            self._settings["planning_model"] = planning_model_input.text
        if verification_model_input is not None:
            self._settings["verification_model"] = verification_model_input.text

        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _YAML_AVAILABLE:
            try:
                with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self._settings, f, default_flow_style=False)
                self._set_status("Settings saved.")
            except Exception:
                logger.exception("Failed to write %s", SETTINGS_PATH)
                self._set_status("Failed to save settings (see logs).")
        else:
            self._set_status("PyYAML not installed; settings not persisted.")

    def _set_status(self, text: str) -> None:
        status_label = self.ids.get("settings_status_label")
        if status_label is not None:
            status_label.text = text

    # -- widget population -------------------------------------------------

    def _populate_widgets(self) -> None:
        backend_spinner = self.ids.get("backend_spinner")
        if backend_spinner is not None:
            backend_spinner.values = BACKEND_CHOICES
            backend_spinner.text = self._settings.get("backend", "Native")

        planning_model_input = self.ids.get("planning_model_input")
        if planning_model_input is not None:
            planning_model_input.text = self._settings.get("planning_model", "")

        verification_model_input = self.ids.get("verification_model_input")
        if verification_model_input is not None:
            verification_model_input.text = self._settings.get("verification_model", "")

        self._refresh_directory_list()

    def _refresh_directory_list(self) -> None:
        container = self.ids.get("directory_list")
        if container is None:
            return
        container.clear_widgets()
        for directory in self._settings.get("allowed_directories", []):
            container.add_widget(self._build_directory_row(directory))

    def _build_directory_row(self, directory: str) -> BoxLayout:
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=36, spacing=8)
        row.add_widget(Label(text=directory))
        remove_btn = Button(text="Remove", size_hint_x=None, width=90)
        remove_btn.bind(on_release=lambda *_: self._remove_directory(directory))
        row.add_widget(remove_btn)
        return row

    def add_directory(self) -> None:
        new_dir_input = self.ids.get("new_dir_input")
        if new_dir_input is None or not new_dir_input.text.strip():
            return
        directory = new_dir_input.text.strip()
        dirs = self._settings.setdefault("allowed_directories", [])
        if directory not in dirs:
            dirs.append(directory)
        new_dir_input.text = ""
        self._refresh_directory_list()

    def _remove_directory(self, directory: str) -> None:
        dirs = self._settings.get("allowed_directories", [])
        if directory in dirs:
            dirs.remove(directory)
        self._refresh_directory_list()
