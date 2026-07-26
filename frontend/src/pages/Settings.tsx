import { useEffect, useState } from "react";
import { api, SettingsPayload } from "../api/client";

const DEFAULT_SETTINGS: SettingsPayload = {
  model: "claude-cli/claude-sonnet-5",
  thinking_level: "low",
  show_reasoning: true,
  allowed_directories: [],
};

const THINKING_LEVEL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "off", label: "Off" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "X-High" },
  { value: "adaptive", label: "Adaptive" },
  { value: "max", label: "Max" },
];

export default function Settings() {
  const [settings, setSettings] = useState<SettingsPayload>(DEFAULT_SETTINGS);
  const [newDir, setNewDir] = useState("");
  const [status, setStatus] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setSettings(s))
      .catch(() => {
        // backend unavailable yet - keep defaults
      })
      .finally(() => setLoaded(true));
  }, []);

  function addDirectory() {
    const dir = newDir.trim();
    if (!dir || settings.allowed_directories.includes(dir)) return;
    setSettings((s) => ({ ...s, allowed_directories: [...s.allowed_directories, dir] }));
    setNewDir("");
  }

  function removeDirectory(dir: string) {
    setSettings((s) => ({
      ...s,
      allowed_directories: s.allowed_directories.filter((d) => d !== dir),
    }));
  }

  async function save() {
    try {
      await api.saveSettings(settings);
      setStatus("Settings saved.");
    } catch (e) {
      setStatus(
        e instanceof Error ? `Failed to save: ${e.message}` : "Failed to save settings.",
      );
    }
  }

  return (
    <div className="page">
      <h1 className="page-title">Settings</h1>
      {!loaded && <div className="empty-state">Loading settings...</div>}

      <div className="settings-section panel">
        <div className="settings-row">
          <span
            className="label"
            title="OpenClaw model id (see `openclaw models list`); swap for a locally-imported model later without code changes"
          >
            Model
          </span>
          <input
            type="text"
            value={settings.model}
            onChange={(e) => setSettings((s) => ({ ...s, model: e.target.value }))}
          />
        </div>
        <div className="field-hint">
          OpenClaw model id (see <code>openclaw models list</code>); swap for a locally-imported
          model later without code changes.
        </div>

        <div className="settings-row">
          <span className="label">Thinking level</span>
          <select
            value={settings.thinking_level}
            onChange={(e) => setSettings((s) => ({ ...s, thinking_level: e.target.value }))}
          >
            {THINKING_LEVEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="settings-row">
          <span className="label">Show reasoning</span>
          <input
            type="checkbox"
            checked={settings.show_reasoning}
            onChange={(e) => setSettings((s) => ({ ...s, show_reasoning: e.target.checked }))}
          />
        </div>
      </div>

      <div className="settings-section panel">
        <span className="field-label">Allow-listed directories:</span>
        <div className="dir-list">
          {settings.allowed_directories.length === 0 ? (
            <div className="empty-state">No directories allow-listed yet.</div>
          ) : (
            settings.allowed_directories.map((dir) => (
              <div className="dir-row" key={dir}>
                <span className="path">{dir}</span>
                <button onClick={() => removeDirectory(dir)}>Remove</button>
              </div>
            ))
          )}
        </div>
        <div className="add-dir-row">
          <input
            type="text"
            placeholder="~/Documents"
            value={newDir}
            onChange={(e) => setNewDir(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") addDirectory();
            }}
          />
          <button onClick={addDirectory}>Add</button>
        </div>
      </div>

      <button className="primary" onClick={save}>
        Save Settings
      </button>
      <div className="save-status">{status}</div>
    </div>
  );
}
