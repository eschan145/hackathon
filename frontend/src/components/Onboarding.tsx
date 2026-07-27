import { useState } from "react";
import { api } from "../api/client";
import { ApprovalMode, useStore } from "../store";
import OrchestratrLogo from "./OrchestratrLogo";

const STEPS = [
  {
    title: "Welcome to Orchestratr",
    body: "Tell Orchestratr what you need, follow its progress, and step in only when necessary.",
  },
  {
    title: "Choose folder access",
    body: "You can limit Orchestratr to specific folders at any time in Settings.",
  },
  {
    title: "Stay in control",
    body: "Orchestratr pauses before high-impact actions and clearly explains what will change.",
  },
  {
    title: "Available from anywhere",
    body: "Move your pointer to the right edge of the screen or press ⌥Space to open the quick overlay.",
  },
];

export default function Onboarding() {
  const { setQuickAddOpen, setApprovalMode } = useStore();
  const [step, setStep] = useState(0);
  const [folder, setFolder] = useState("");
  const [mode, setMode] = useState<ApprovalMode>("ask");
  const [visible, setVisible] = useState(() => localStorage.getItem("orchestratr.onboarding.v2") !== "done");

  if (!visible) return null;
  const current = STEPS[step];

  function finish(createTask = false) {
    localStorage.setItem("orchestratr.onboarding.v2", "done");
    setVisible(false);
    if (createTask) setQuickAddOpen(true);
  }

  async function continueOnboarding() {
    if (step === 1 && folder.trim()) {
      try {
        const settings = await api.getSettings();
        if (!settings.allowed_directories.includes(folder.trim())) {
          await api.saveSettings({
            ...settings,
            allowed_directories: [...settings.allowed_directories, folder.trim()],
          });
        }
      } catch {
        // Settings can still be completed later if the backend is offline.
      }
    }
    if (step === 2) setApprovalMode(mode);
    if (step === STEPS.length - 1) finish(true);
    else setStep((value) => value + 1);
  }

  return (
    <div className="onboarding-backdrop">
      <section className="onboarding-card" role="dialog" aria-modal="true" aria-label="Welcome to Orchestratr">
        <OrchestratrLogo size={44} wordmark />
        <div className="onboarding-progress" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((_, index) => <span className={index <= step ? "active" : ""} key={index} />)}
        </div>
        <div className="onboarding-copy">
          <small>{step + 1} of {STEPS.length}</small>
          <h1>{current.title}</h1>
          <p>{current.body}</p>
          {step === 1 && (
            <label className="onboarding-folder">
              <span>Allowed folder</span>
              <input value={folder} onChange={(event) => setFolder(event.target.value)} placeholder="/Users/you/Documents" />
            </label>
          )}
          {step === 2 && (
            <div className="onboarding-choices">
              <button className={mode === "ask" ? "selected" : ""} onClick={() => setMode("ask")}><strong>Ask first</strong><span>Pause for high-impact actions</span></button>
              <button className={mode === "auto" ? "selected" : ""} onClick={() => setMode("auto")}><strong>Run autonomously</strong><span>Continue without asking</span></button>
            </div>
          )}
          {step === 3 && <div className="shortcut-preview">⌥ <span>Space</span></div>}
        </div>
        <div className="onboarding-actions">
          <button className="text-button" onClick={() => finish(false)}>Skip</button>
          <button className="primary-button" onClick={() => void continueOnboarding()}>
            {step === STEPS.length - 1 ? "Create first task" : "Continue"}
          </button>
        </div>
      </section>
    </div>
  );
}
