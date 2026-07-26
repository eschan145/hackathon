import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { CloseIcon, LinkIcon, PaperclipIcon, SendIcon } from "../lib/icons";
import { useStore } from "../store";

interface Attachment {
  id: string;
  label: string;
  /** Absolute path when running under Electron, bare filename in a browser. */
  path: string;
}

interface TaskComposerProps {
  variant: "inline" | "modal";
  autoFocus?: boolean;
  onCreated?: (taskId: string) => void;
}

/**
 * The backend currently accepts one objective string. Keep the user's task as
 * the first line (so task-list titles stay useful), then add the optional
 * execution context in clearly labeled sections for the planner.
 */
function composeObjective(
  objective: string,
  procedure: string,
  files: Attachment[],
  links: string[],
): string {
  const parts = [objective.trim()];
  if (procedure.trim()) parts.push(`Plan or procedure:\n${procedure.trim()}`);
  if (files.length) parts.push(`Files to work with:\n${files.map((file) => `- ${file.path}`).join("\n")}`);
  if (links.length) parts.push(`Links to use:\n${links.map((link) => `- ${link}`).join("\n")}`);
  return parts.join("\n\n");
}

function normalizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  return /^[a-z][a-z\d+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function linksFromDraft(draft: string): string[] {
  return draft
    .split(/[\s,]+/)
    .map(normalizeUrl)
    .filter(Boolean);
}

function mergeLinks(current: string[], draft: string): string[] {
  return [...new Set([...current, ...linksFromDraft(draft)])];
}

export default function TaskComposer({ variant, autoFocus, onCreated }: TaskComposerProps) {
  const { createTask } = useStore();
  const [objective, setObjective] = useState("");
  const [procedure, setProcedure] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const objectiveRef = useRef<HTMLTextAreaElement>(null);
  const procedureRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    for (const el of [objectiveRef.current, procedureRef.current]) {
      if (!el) continue;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, variant === "modal" ? 180 : 220)}px`;
    }
  }, [objective, procedure, variant]);

  function reset() {
    setObjective("");
    setProcedure("");
    setFiles([]);
    setLinks([]);
    setLinkDraft("");
    setError(null);
  }

  function pickFiles(list: FileList | null) {
    if (!list?.length) return;
    const picked: Attachment[] = Array.from(list).map((file, index) => ({
      id: `${Date.now()}-${index}`,
      label: file.name,
      // Electron 31 exposes the real path; browsers only expose the filename.
      path: (file as File & { path?: string }).path || file.name,
    }));
    setFiles((current) => {
      const knownPaths = new Set(current.map((file) => file.path));
      return [...current, ...picked.filter((file) => !knownPaths.has(file.path))];
    });
  }

  function addLinks() {
    const next = mergeLinks(links, linkDraft);
    if (next.length === links.length) return;
    setLinks(next);
    setLinkDraft("");
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!objective.trim() || submitting) return;

    const submittedLinks = mergeLinks(links, linkDraft);
    setSubmitting(true);
    setError(null);
    try {
      const taskId = await createTask(
        composeObjective(objective, procedure, files, submittedLinks),
        "gui",
      );
      reset();
      onCreated?.(taskId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  function submitShortcut(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form className={`task-composer ${variant}`} onSubmit={submit}>
      <div className="task-composer-header">
        <div>
          <h2>{variant === "inline" ? "Add a task" : "Quick add task"}</h2>
          <p>Give the assistant the goal and any context it should follow.</p>
        </div>
        <span className="composer-shortcut">⌘/Ctrl + Enter to add</span>
      </div>

      <div className="task-composer-fields">
        <label className="composer-field">
          <span className="composer-label">What should it do?</span>
          <textarea
            ref={objectiveRef}
            autoFocus={autoFocus}
            rows={3}
            value={objective}
            placeholder="Describe the result you want…"
            onChange={(event) => setObjective(event.target.value)}
            onKeyDown={submitShortcut}
          />
        </label>

        <label className="composer-field">
          <span className="composer-label">
            Plan or procedure
            <span className="composer-optional">Optional</span>
          </span>
          <textarea
            ref={procedureRef}
            rows={2}
            value={procedure}
            placeholder="Explain how it should approach the task, constraints to follow, or steps to take…"
            onChange={(event) => setProcedure(event.target.value)}
            onKeyDown={submitShortcut}
          />
        </label>

        <div className="composer-field">
          <label className="composer-label" htmlFor={`task-links-${variant}`}>
            Links
            <span className="composer-optional">Optional</span>
          </label>
          <div className="composer-link-control">
            <LinkIcon size={15} />
            <input
              id={`task-links-${variant}`}
              type="text"
              inputMode="url"
              value={linkDraft}
              placeholder="Paste one or more links"
              onChange={(event) => setLinkDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addLinks();
                }
              }}
            />
            <button type="button" className="btn-quiet" onClick={addLinks} disabled={!linkDraft.trim()}>
              Add
            </button>
          </div>
          <span className="composer-field-hint">Separate multiple links with spaces or new lines.</span>
        </div>
      </div>

      {(files.length > 0 || links.length > 0) && (
        <div className="composer-resources" aria-label="Task resources">
          {files.map((file) => (
            <span className="chip" key={file.id} title={file.path}>
              <PaperclipIcon size={13} />
              <span>{file.label}</span>
              <button
                type="button"
                onClick={() => setFiles((current) => current.filter((item) => item.id !== file.id))}
                aria-label={`Remove ${file.label}`}
              >
                <CloseIcon size={12} />
              </button>
            </span>
          ))}
          {links.map((link) => (
            <span className="chip" key={link} title={link}>
              <LinkIcon size={13} />
              <span>{link.replace(/^https?:\/\//, "")}</span>
              <button
                type="button"
                onClick={() => setLinks((current) => current.filter((item) => item !== link))}
                aria-label={`Remove ${link}`}
              >
                <CloseIcon size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="composer-actions">
        <button type="button" className="tool-btn" onClick={() => fileInputRef.current?.click()}>
          <PaperclipIcon size={15} />
          Attach files
        </button>
        <span className="composer-action-hint">Files stay local and are passed to the assistant by path.</span>
        <button type="submit" className="btn-primary" disabled={!objective.trim() || submitting}>
          <SendIcon size={15} />
          {submitting ? "Adding…" : "Add task"}
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          pickFiles(event.target.files);
          event.target.value = "";
        }}
      />

      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
    </form>
  );
}
