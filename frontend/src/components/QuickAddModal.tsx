import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CloseIcon, LinkIcon, PaperclipIcon, SendIcon } from "../lib/icons";
import { useStore } from "../store";

interface Attachment {
  id: string;
  label: string;
  /** Absolute path when running under Electron, bare filename in a browser. */
  path: string;
}

/**
 * The backend takes only an objective string (POST /api/objectives), so
 * attachments are appended as plain-text context the local planner can act
 * on — absolute paths for files, bare URLs for sites to work in.
 */
function composeObjective(text: string, files: Attachment[], links: string[]): string {
  const parts = [text.trim()];
  if (files.length) parts.push(`Files to work with:\n${files.map((f) => `- ${f.path}`).join("\n")}`);
  if (links.length) parts.push(`Work in these sites:\n${links.map((l) => `- ${l}`).join("\n")}`);
  return parts.join("\n\n");
}

function normalizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  return /^[a-z]+:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

export default function QuickAddModal() {
  const { quickAddOpen, setQuickAddOpen, createTask } = useStore();
  const navigate = useNavigate();

  const [text, setText] = useState("");
  const [files, setFiles] = useState<Attachment[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [linkOpen, setLinkOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const linkRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!quickAddOpen) return;
    setText("");
    setFiles([]);
    setLinks([]);
    setLinkDraft("");
    setLinkOpen(false);
    setError(null);
  }, [quickAddOpen]);

  useEffect(() => {
    if (linkOpen) linkRef.current?.focus();
  }, [linkOpen]);

  // Grow the composer with its content, ChatGPT-style.
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [text, quickAddOpen]);

  if (!quickAddOpen) return null;

  function pickFiles(list: FileList | null) {
    if (!list?.length) return;
    const picked: Attachment[] = Array.from(list).map((f, i) => ({
      id: `${Date.now()}-${i}`,
      label: f.name,
      // Electron exposes the real path on File; a plain browser does not.
      path: (f as File & { path?: string }).path || f.name,
    }));
    setFiles((prev) => [...prev, ...picked]);
  }

  function addLink() {
    const url = normalizeUrl(linkDraft);
    if (!url || links.includes(url)) return;
    setLinks((prev) => [...prev, url]);
    setLinkDraft("");
  }

  async function submit() {
    if (!text.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const taskId = await createTask(composeObjective(text, files, links), "gui");
      setQuickAddOpen(false);
      navigate(`/chat/${taskId}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the backend.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={() => setQuickAddOpen(false)}>
      <div className="composer-modal" role="dialog" aria-modal onMouseDown={(e) => e.stopPropagation()}>
        <div className="composer-shell">
          <textarea
            ref={textRef}
            autoFocus
            rows={1}
            value={text}
            placeholder="What should the assistant do?"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />

          {(files.length > 0 || links.length > 0) && (
            <div className="chips">
              {files.map((f) => (
                <span className="chip" key={f.id} title={f.path}>
                  <PaperclipIcon size={13} />
                  {f.label}
                  <button
                    onClick={() => setFiles((prev) => prev.filter((x) => x.id !== f.id))}
                    aria-label={`Remove ${f.label}`}
                  >
                    <CloseIcon size={12} />
                  </button>
                </span>
              ))}
              {links.map((l) => (
                <span className="chip" key={l} title={l}>
                  <LinkIcon size={13} />
                  {l.replace(/^https?:\/\//, "")}
                  <button
                    onClick={() => setLinks((prev) => prev.filter((x) => x !== l))}
                    aria-label={`Remove ${l}`}
                  >
                    <CloseIcon size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}

          {linkOpen && (
            <div className="link-row">
              <input
                ref={linkRef}
                value={linkDraft}
                placeholder="amazon.com"
                onChange={(e) => setLinkDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addLink();
                  }
                  if (e.key === "Escape") setLinkOpen(false);
                }}
              />
              <button className="btn-quiet" onClick={addLink} disabled={!linkDraft.trim()}>
                Add link
              </button>
            </div>
          )}

          <div className="composer-tools">
            <button className="tool-btn" onClick={() => fileInputRef.current?.click()}>
              <PaperclipIcon size={15} />
              Attach files
            </button>
            <button className="tool-btn" onClick={() => setLinkOpen((o) => !o)}>
              <LinkIcon size={15} />
              Add link
            </button>
            <span className="composer-hint">Enter to send · Shift+Enter for a new line</span>
            <button
              className="btn-primary send"
              onClick={submit}
              disabled={!text.trim() || submitting}
              aria-label="Add task"
            >
              <SendIcon size={15} />
            </button>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              pickFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {error && <div className="form-error">{error}</div>}
      </div>
    </div>
  );
}
