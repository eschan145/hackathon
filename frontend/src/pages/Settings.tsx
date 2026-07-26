import { useEffect, useState } from "react";
import { CloseIcon, PlusIcon } from "../lib/icons";
import { api, SettingsPayload } from "../api/client";
import { ApprovalMode, useStore } from "../store";

const APPROVAL_OPTIONS: Array<{ value: ApprovalMode; label: string; hint: string }> = [
  {
    value: "ask",
    label: "Ask for high-risk actions",
    hint: "Purchases, sending, and destructive changes wait for your decision.",
  },
  {
    value: "auto",
    label: "Run autonomously",
    hint: "High-risk actions continue without confirmation while Orchestratr is open.",
  },
];

const DEFAULT_SETTINGS: SettingsPayload = {
  backend: "OpenClaw",
  planning_model: "llama-3.1-70b-instruct",
  verification_model: "nemotron-vision-small",
  allowed_directories: [],
};

export default function Settings() {
  const { approvalMode, setApprovalMode } = useStore();
  const [settings, setSettings] = useState<SettingsPayload>(DEFAULT_SETTINGS);
  const [newDir, setNewDir] = useState("");
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [overlay, setOverlay] = useState(() => {
    try {
      return {
        enabled: localStorage.getItem("orchestratr.overlay.enabled") !== "false",
        edge: (localStorage.getItem("orchestratr.overlay.edge") === "left" ? "left" : "right") as "left" | "right",
        delay: Number(localStorage.getItem("orchestratr.overlay.delay") ?? 350),
        launchAtLogin: localStorage.getItem("orchestratr.launchAtLogin") !== "false",
      };
    } catch {
      return { enabled: true, edge: "right" as const, delay: 350, launchAtLogin: true };
    }
  });

  useEffect(() => {
    api
      .getSettings()
      .then((s) => setSettings({ ...DEFAULT_SETTINGS, ...s, backend: "OpenClaw" }))
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
      // Keep the live approval mode authoritative — it may have changed
      // since this page loaded its copy of the settings.
      await api.saveSettings({ ...settings, backend: "OpenClaw", approval_mode: approvalMode });
      localStorage.setItem("orchestratr.overlay.enabled", String(overlay.enabled));
      localStorage.setItem("orchestratr.overlay.edge", overlay.edge);
      localStorage.setItem("orchestratr.overlay.delay", String(overlay.delay));
      localStorage.setItem("orchestratr.launchAtLogin", String(overlay.launchAtLogin));
      window.orchestratrDesktop?.configureOverlay(overlay);
      setStatus({ kind: "ok", text: "Settings saved." });
    } catch (e) {
      setStatus({
        kind: "err",
        text: e instanceof Error ? `Failed to save: ${e.message}` : "Failed to save settings.",
      });
    }
  }

  return (
    <div className="view settings-view">
      <header className="settings-header">
        <h1>Settings</h1>
        <p>Control approvals, access, and the quick overlay.</p>
      </header>

      <div className="settings-content">
        {!loaded && <div className="banner subtle">Loading settings…</div>}

        <section className="setting-block">
          <div className="setting-intro">
            <div>
              <h2>Approvals</h2>
              <p>Choose when a high-risk step must stop and ask you first.</p>
            </div>
          </div>
          <p className="panel-note">
            Low and medium-risk work continues automatically. Autonomous approval only applies while
            this app is open.
          </p>
          <div className="choice-list">
            {APPROVAL_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={`choice${approvalMode === opt.value ? " selected" : ""}`}
                onClick={() => setApprovalMode(opt.value)}
              >
                <span className="choice-radio" aria-hidden />
                <span className="choice-copy">
                  <span className="choice-name">{opt.label}</span>
                  <span className="choice-hint">{opt.hint}</span>
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="setting-block">
          <div className="setting-intro">
            <div>
              <h2>Allowed folders</h2>
              <p>Orchestratr can only read and write inside these folders.</p>
            </div>
          </div>
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
              aria-label="Directory path"
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

        <section className="setting-block">
          <div className="setting-intro">
            <div>
              <h2>Quick overlay</h2>
              <p>Open Orchestratr from the edge of your screen or with ⌥Space.</p>
            </div>
          </div>
          <div className="settings-grid">
            <label className="toggle-row">
              <span><strong>Edge activation</strong><small>Show the overlay when the pointer reaches the screen edge.</small></span>
              <input type="checkbox" checked={overlay.enabled} onChange={(event) => setOverlay((value) => ({ ...value, enabled: event.target.checked }))} />
            </label>
            <label className="field-row">
              <span><strong>Screen edge</strong><small>Choose where the hidden trigger appears.</small></span>
              <select value={overlay.edge} onChange={(event) => setOverlay((value) => ({ ...value, edge: event.target.value as "left" | "right" }))}>
                <option value="right">Right</option>
                <option value="left">Left</option>
              </select>
            </label>
            <label className="field-row">
              <span><strong>Activation delay</strong><small>Prevents accidental opening.</small></span>
              <select value={overlay.delay} onChange={(event) => setOverlay((value) => ({ ...value, delay: Number(event.target.value) }))}>
                <option value={150}>Fast · 150ms</option>
                <option value={350}>Balanced · 350ms</option>
                <option value={650}>Relaxed · 650ms</option>
              </select>
            </label>
            <label className="toggle-row">
              <span><strong>Launch at login</strong><small>Keep Orchestratr available in the menu bar.</small></span>
              <input type="checkbox" checked={overlay.launchAtLogin} onChange={(event) => setOverlay((value) => ({ ...value, launchAtLogin: event.target.checked }))} />
            </label>
          </div>
        </section>

        <div className="settings-actions">
          <button className="btn-primary" onClick={save}>
            Save changes
          </button>
          {status && <span className={`save-status ${status.kind}`}>{status.text}</span>}
        </div>
      </div>
    </div>
  );
}
