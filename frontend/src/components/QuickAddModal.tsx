import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { CloseIcon } from "../lib/icons";
import { useStore } from "../store";
import TaskComposer from "./TaskComposer";

export default function QuickAddModal() {
  const { quickAddOpen, setQuickAddOpen } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (!quickAddOpen) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setQuickAddOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [quickAddOpen, setQuickAddOpen]);

  if (!quickAddOpen) return null;

  return (
    <div className="modal-overlay" onMouseDown={() => setQuickAddOpen(false)}>
      <div
        className="composer-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Quick add task"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button
          className="composer-modal-close"
          onClick={() => setQuickAddOpen(false)}
          aria-label="Close quick add"
        >
          <CloseIcon size={16} />
        </button>
        <TaskComposer
          variant="modal"
          autoFocus
          onCreated={(taskId) => {
            setQuickAddOpen(false);
            navigate(`/chat/${taskId}`);
          }}
        />
      </div>
    </div>
  );
}
