import {
  ClipboardEvent,
  DragEvent,
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { CloseIcon, LinkIcon, PaperclipIcon, PlusIcon, SendIcon } from "../lib/icons";
import { useStore } from "../store";

interface Attachment {
  id: string;
  label: string;
  path: string;
}

interface TaskComposerProps {
  variant: "inline" | "modal";
  autoFocus?: boolean;
  onCreated?: (taskId: string) => void;
}

function composeObjective(objective: string, files: Attachment[], links: string[]): string {
  const parts = [objective.trim()];
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
  const [files, setFiles] = useState<Attachment[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [expanded, setExpanded] = useState(variant === "modal");
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const objectiveRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = objectiveRef.current;
    if (!el) return;
    el.style.height = "auto";
    const max = variant === "modal" ? 210 : 170;
    el.style.height = `${Math.min(Math.max(el.scrollHeight, expanded ? 68 : 28), max)}px`;
  }, [objective, expanded, variant]);

  function reset() {
    setObjective("");
    setFiles([]);
    setLinks([]);
    setLinkDraft("");
    setError(null);
    if (variant === "inline") setExpanded(false);
  }

  function pickFiles(list: FileList | File[]) {
    const pickedFiles = Array.from(list);
    if (!pickedFiles.length) return;
    const picked: Attachment[] = pickedFiles.map((file, index) => ({
      id: `${Date.now()}-${index}`,
      label: file.name,
      path: (file as File & { path?: string }).path || file.name,
    }));
    setFiles((current) => {
      const knownPaths = new Set(current.map((file) => file.path));
      return [...current, ...picked.filter((file) => !knownPaths.has(file.path))];
    });
    setExpanded(true);
  }

  function addLinks() {
    const next = mergeLinks(links, linkDraft);
    if (next.length === links.length) return;
    setLinks(next);
    setLinkDraft("");
    setExpanded(true);
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = event.clipboardData.getData("text").trim();
    if (!pasted || !/^https?:\/\/\S+(?:[\s,]+https?:\/\/\S+)*$/i.test(pasted)) return;
    event.preventDefault();
    setLinks((current) => mergeLinks(current, pasted));
    setExpanded(true);
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const trimmed = objective.trim();
    if (!trimmed || submitting) return;
    const words = trimmed.split(/\s+/).filter(Boolean);
    if (words.length < 2 && files.length === 0 && links.length === 0) {
      setExpanded(true);
      setError("Add a little more detail or attach a source for Orchestratr to use.");
      return;
    }

    const submittedLinks = mergeLinks(links, linkDraft);
    setSubmitting(true);
    setError(null);
    try {
      const taskId = await createTask(composeObjective(trimmed, files, submittedLinks), "gui");
      reset();
      onCreated?.(taskId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not reach the local engine.");
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

  function onDrop(event: DragEvent<HTMLFormElement>) {
    event.preventDefault();
    setDragging(false);
    pickFiles(event.dataTransfer.files);
  }

  const hasResources = files.length > 0 || links.length > 0;

  return (
    <form
      className={`task-composer ${variant}${expanded ? " expanded" : ""}${dragging ? " dragging" : ""}`}
      onSubmit={submit}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragging(false);
      }}
      onDrop={onDrop}
    >
      <div className="composer-main">
        <span className="composer-plus" aria-hidden>
          <PlusIcon size={18} />
        </span>
        <textarea
          ref={objectiveRef}
          autoFocus={autoFocus}
          rows={1}
          value={objective}
          aria-label="New task"
          placeholder="What would you like Orchestratr to do?"
          onFocus={() => setExpanded(true)}
          onChange={(event) => {
            setObjective(event.target.value);
            if (error) setError(null);
          }}
          onPaste={handlePaste}
          onKeyDown={submitShortcut}
        />
        <button
          type="submit"
          className="composer-launch"
          disabled={!objective.trim() || submitting}
          aria-label="Start task"
        >
          {submitting ? <span className="mini-spinner" /> : <SendIcon size={16} />}
          <span>{submitting ? "Starting" : "Start task"}</span>
        </button>
      </div>

      {(expanded || hasResources) && (
        <div className="composer-detail">
          {hasResources && (
            <div className="composer-resources" aria-label="Task resources">
              {files.map((file) => (
                <span className="resource-chip" key={file.id} title={file.path}>
                  <PaperclipIcon size={13} />
                  <span>{file.label}</span>
                  <button
                    type="button"
                    onClick={() => setFiles((current) => current.filter((item) => item.id !== file.id))}
                    aria-label={`Remove ${file.label}`}
                  >
                    <CloseIcon size={11} />
                  </button>
                </span>
              ))}
              {links.map((link) => (
                <span className="resource-chip" key={link} title={link}>
                  <LinkIcon size={13} />
                  <span>{link.replace(/^https?:\/\//, "")}</span>
                  <button
                    type="button"
                    onClick={() => setLinks((current) => current.filter((item) => item !== link))}
                    aria-label={`Remove ${link}`}
                  >
                    <CloseIcon size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="composer-tools">
            <button type="button" className="composer-tool" onClick={() => fileInputRef.current?.click()}>
              <PaperclipIcon size={15} />
              Attach
            </button>
            <div className="link-tool">
              <LinkIcon size={15} />
              <input
                type="text"
                inputMode="url"
                value={linkDraft}
                aria-label="Add links"
                placeholder="Paste a link"
                onChange={(event) => setLinkDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addLinks();
                  }
                }}
              />
              {linkDraft && (
                <button type="button" onClick={addLinks}>
                  Add
                </button>
              )}
            </div>
            <span className="composer-hint">⌘↵ to start · drop files anywhere</span>
          </div>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          if (event.target.files) pickFiles(event.target.files);
          event.target.value = "";
        }}
      />

      {dragging && <div className="drop-message">Drop files to add context</div>}
      {error && <div className="form-error" role="alert">{error}</div>}
    </form>
  );
}
