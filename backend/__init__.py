"""FastAPI backend for the Electron/React frontend.

Wires the same core/planning/execution/verification/memory subsystems used
by gui/main.py's build_orchestrator() behind an HTTP + WebSocket API so a
non-Kivy frontend can drive the assistant. See backend/main.py.
"""
