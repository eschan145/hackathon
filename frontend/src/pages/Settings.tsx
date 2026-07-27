import { useEffect, useState } from "react";
import { CloseIcon, PlusIcon } from "../lib/icons";
import { api, SettingsPayload } from "../api/client";
import { ApprovalMode, useStore } from "../store";

const APPROVAL_OPTIONS: Array<{ value: ApprovalMode; label: string; hint: string }> = [
  { value: "ask", label: "Ask for high-risk actions", hint: "Purchases, sending, and destructive changes wait for your decision." },
  { value: "auto", label: "Run autonomously", hint: "High-risk actions continue without confirmation while Orchestratr is open." },
];

const DEFAULT_SETTINGS: SettingsPayload = {
  model: "ollama/qwen3-vl:30b-a3b",
  thinking_level: "low",
  show_reasoning: true,
  allowed_directories: [],
};

const THINKING_LEVEL_OPTIONS = ["off", "minimal", "low", "medium", "high", "xhigh", "adaptive", "max"];

export default function Settings() {
  const { approvalMode, setApprovalMode } = useStore();
  const [settings, setSettings] = useState<SettingsPayload>(DEFAULT_SETTINGS);
  const [newDir, setNewDir] = useState("");
  const [status, setStatus] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [overlay, setOverlay] = useState(() => ({
    enabled: localStorage.getItem("orchestratr.overlay.enabled") !== "false",
    edge: (localStorage.getItem("orchestratr.overlay.edge") === "left" ? "left" : "right") as "left" | "right",
    delay: Number(localStorage.getItem("orchestratr.overlay.delay") ?? 350),
    launchAtLogin: localStorage.getItem("orchestratr.launchAtLogin") !== "false",
  }));

  useEffect(() => {
    api.getSettings().then((value) => setSettings({ ...DEFAULT_SETTINGS, ...value })).catch(() => undefined).finally(() => setLoaded(true));
  }, []);

  function addDirectory() {
    const dir = newDir.trim();
    if (!dir || settings.allowed_directories.includes(dir)) return;
    setSettings((value) => ({ ...value, allowed_directories: [...value.allowed_directories, dir] }));
    setNewDir("");
  }

  async function save() {
    try {
      await api.saveSettings({ ...settings, approval_mode: approvalMode });
      localStorage.setItem("orchestratr.overlay.enabled", String(overlay.enabled));
      localStorage.setItem("orchestratr.overlay.edge", overlay.edge);
      localStorage.setItem("orchestratr.overlay.delay", String(overlay.delay));
      localStorage.setItem("orchestratr.launchAtLogin", String(overlay.launchAtLogin));
      window.orchestratrDesktop?.configureOverlay(overlay);
      setStatus({ kind: "ok", text: "Settings saved." });
    } catch (error) {
      setStatus({ kind: "err", text: error instanceof Error ? `Failed to save: ${error.message}` : "Failed to save settings." });
    }
  }

  return (
    <div className="view settings-view">
      <header className="settings-header"><h1>Settings</h1><p>Control approvals, local execution, access, and the quick overlay.</p></header>
      <div className="settings-content">
        {!loaded && <div className="banner subtle">Loading settings…</div>}
        <section className="setting-block">
          <div className="setting-intro"><div><h2>Approvals</h2><p>Choose when a high-risk step must stop and ask you first.</p></div></div>
          <p className="panel-note">Low and medium-risk work continues automatically. Autonomous approval only applies while this app is open.</p>
          <div className="choice-list">
            {APPROVAL_OPTIONS.map((option) => <button key={option.value} className={`choice${approvalMode === option.value ? " selected" : ""}`} onClick={() => setApprovalMode(option.value)}><span className="choice-radio" aria-hidden /><span className="choice-copy"><span className="choice-name">{option.label}</span><span className="choice-hint">{option.hint}</span></span></button>)}
          </div>
        </section>
        <section className="setting-block">
          <div className="setting-intro"><div><h2>Local model</h2><p>This installation uses a local Qwen model; cloud models are disabled.</p></div></div>
          <div className="settings-grid">
            <label className="field-row"><span><strong>Model</strong><small>Fixed by the local runtime.</small></span><input value={settings.model} readOnly disabled /></label>
            <label className="field-row"><span><strong>Thinking level</strong><small>Controls how deeply the model reasons.</small></span><select value={settings.thinking_level} onChange={(event) => setSettings((value) => ({ ...value, thinking_level: event.target.value }))}>{THINKING_LEVEL_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            <label className="toggle-row"><span><strong>Show reasoning</strong><small>Include live planning and execution details in task chats.</small></span><input type="checkbox" checked={settings.show_reasoning} onChange={(event) => setSettings((value) => ({ ...value, show_reasoning: event.target.checked }))} /></label>
          </div>
        </section>
        <section className="setting-block">
          <div className="setting-intro"><div><h2>Allowed folders</h2><p>Orchestratr can only read and write inside these folders.</p></div></div>
          <div className="dir-list">{settings.allowed_directories.length === 0 ? <p className="setting-hint">No directories allow-listed yet.</p> : settings.allowed_directories.map((dir) => <div className="dir-row" key={dir}><code>{dir}</code><button className="icon-btn sm" onClick={() => setSettings((value) => ({ ...value, allowed_directories: value.allowed_directories.filter((entry) => entry !== dir) }))} aria-label="Remove"><CloseIcon size={15} /></button></div>)}</div>
          <div className="dir-add"><input placeholder="/Users/you/Documents" aria-label="Directory path" value={newDir} onChange={(event) => setNewDir(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") addDirectory(); }} /><button className="btn-ghost" onClick={addDirectory}><PlusIcon size={14} />Add</button></div>
        </section>
        <section className="setting-block">
          <div className="setting-intro"><div><h2>Quick overlay</h2><p>Open Orchestratr from the edge of your screen or with ⌥Space.</p></div></div>
          <div className="settings-grid">
            <label className="toggle-row"><span><strong>Edge activation</strong><small>Show the overlay when the pointer reaches the screen edge.</small></span><input type="checkbox" checked={overlay.enabled} onChange={(event) => setOverlay((value) => ({ ...value, enabled: event.target.checked }))} /></label>
            <label className="field-row"><span><strong>Screen edge</strong><small>Choose where the hidden trigger appears.</small></span><select value={overlay.edge} onChange={(event) => setOverlay((value) => ({ ...value, edge: event.target.value as "left" | "right" }))}><option value="right">Right</option><option value="left">Left</option></select></label>
            <label className="field-row"><span><strong>Activation delay</strong><small>Prevents accidental opening.</small></span><select value={overlay.delay} onChange={(event) => setOverlay((value) => ({ ...value, delay: Number(event.target.value) }))}><option value={150}>Fast · 150ms</option><option value={350}>Balanced · 350ms</option><option value={650}>Relaxed · 650ms</option></select></label>
            <label className="toggle-row"><span><strong>Launch at login</strong><small>Keep Orchestratr available in the menu bar.</small></span><input type="checkbox" checked={overlay.launchAtLogin} onChange={(event) => setOverlay((value) => ({ ...value, launchAtLogin: event.target.checked }))} /></label>
          </div>
        </section>
        <div className="settings-actions"><button className="btn-primary" onClick={save}>Save changes</button>{status && <span className={`save-status ${status.kind}`}>{status.text}</span>}</div>
      </div>
    </div>
  );
}
