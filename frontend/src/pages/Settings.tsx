import { useEffect, useState } from "react";
import { api, SettingsPayload } from "../api/client";

const DEFAULT_SETTINGS: SettingsPayload = {
  backend: "Native",
  planning_model: "llama-3.1-70b-instruct",
  verification_model: "nemotron-vision-small",
  allowed_directories: [],
};

const BACKEND_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "Native", label: "Native" },
  { value: "OpenClaw", label: "OpenClaw (real working backend)" },
  { value: "NemoClaw", label: "NemoClaw" },
  { value: "OpenShell", label: "OpenShell" },
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
          <span className="label" title="OpenClaw is the real working control backend for this hackathon build">
            Control backend
          </span>
          <select
            value={settings.backend}
            onChange={(e) => setSettings((s) => ({ ...s, backend: e.target.value }))}
          >
            {BACKEND_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="settings-row">
          <span className="label">Planning model</span>
          <input
            type="text"
            value={settings.planning_model}
            onChange={(e) => setSettings((s) => ({ ...s, planning_model: e.target.value }))}
          />
        </div>

        <div className="settings-row">
          <span className="label">Verification model</span>
          <input
            type="text"
            value={settings.verification_model}
            onChange={(e) => setSettings((s) => ({ ...s, verification_model: e.target.value }))}
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
            placeholder="C:\path\to\allow"
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
