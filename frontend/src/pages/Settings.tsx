import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import { CloseIcon, PlusIcon } from "../lib/icons";
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
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setSettings({ ...DEFAULT_SETTINGS, ...s }))
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
      setStatus({ kind: "ok", text: "Settings saved." });
    } catch (e) {
      setStatus({
        kind: "err",
        text: e instanceof Error ? `Failed to save: ${e.message}` : "Failed to save settings.",
      });
    }
  }

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Execution backend, local models, and filesystem guardrails"
        help={[
          "Control backend selects which automation layer executes steps.",
          "Models run locally — names must match what's loaded on the DGX Spark.",
          "Allow-listed directories bound where the agent may read and write.",
        ]}
      />

      <div className="page-body settings">
        {!loaded && <div className="banner subtle">Loading settings…</div>}

        <section className="panel">
          <h2 className="panel-title">Execution</h2>
          <div className="setting-row">
            <div className="setting-copy">
              <span className="setting-name">Control backend</span>
              <span className="setting-hint">Layer used to drive the desktop</span>
            </div>
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

          <div className="setting-row">
            <div className="setting-copy">
              <span className="setting-name">Planning model</span>
              <span className="setting-hint">Decomposes objectives into a step DAG</span>
            </div>
            <input
              value={settings.planning_model}
              onChange={(e) => setSettings((s) => ({ ...s, planning_model: e.target.value }))}
            />
          </div>

          <div className="setting-row">
            <div className="setting-copy">
              <span className="setting-name">Verification model</span>
              <span className="setting-hint">Confirms each step actually succeeded</span>
            </div>
            <input
              value={settings.verification_model}
              onChange={(e) => setSettings((s) => ({ ...s, verification_model: e.target.value }))}
            />
          </div>
        </section>

        <section className="panel">
          <h2 className="panel-title">Allow-listed directories</h2>
          <div className="dir-list">
            {settings.allowed_directories.length === 0 ? (
              <p className="setting-hint">No directories allow-listed yet.</p>
            ) : (
              settings.allowed_directories.map((dir) => (
                <div className="dir-row" key={dir}>
                  <code>{dir}</code>
                  <button className="icon-btn sm" onClick={() => removeDirectory(dir)} aria-label="Remove">
                    <CloseIcon size={15} />
                  </button>
                </div>
              ))
            )}
          </div>
          <div className="dir-add">
            <input
              placeholder="/Users/you/Documents"
              value={newDir}
              onChange={(e) => setNewDir(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addDirectory();
              }}
            />
            <button className="btn-ghost" onClick={addDirectory}>
              <PlusIcon size={14} />
              Add
            </button>
          </div>
        </section>

        <div className="settings-actions">
          <button className="btn-primary" onClick={save}>
            Save Settings
          </button>
          {status && <span className={`save-status ${status.kind}`}>{status.text}</span>}
        </div>
      </div>
    </>
  );
}
