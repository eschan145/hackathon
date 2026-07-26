// Intentionally minimal / unused: the renderer connects directly to the
// local backend (http://127.0.0.1:8765) via fetch and WebSocket rather
// than routing through IPC. Kept as a placeholder in case a future
// feature (e.g. native file dialogs) needs a contextBridge API.
export {};
