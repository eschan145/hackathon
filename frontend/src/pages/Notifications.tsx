import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { AlertIcon, CheckCircleIcon, ChipIcon } from "../lib/icons";
import { formatRelative, useStore, useTicker } from "../store";

const ICONS = {
  info: <ChipIcon size={16} />,
  warning: <AlertIcon size={16} />,
  success: <CheckCircleIcon size={16} />,
};

export default function Notifications() {
  const { notifications, markNotificationsRead } = useStore();
  const navigate = useNavigate();
  useTicker();

  // Landing on the view clears the sidebar's unread badge.
  useEffect(() => {
    markNotificationsRead();
  }, [markNotificationsRead, notifications.length]);

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Stay updated with task progressions, updates, and mentions"
        help={[
          "Live feed of orchestrator events: plans, failures, approvals and completions.",
          "Select a notification to jump into that task's chat.",
          "The feed is in-memory and resets when the app restarts.",
        ]}
      />

      <div className="page-body">
        {notifications.length === 0 ? (
          <div className="empty-state">
            <h3>You're all caught up</h3>
            <p>Task progress, approval requests and failures will show up here as they happen.</p>
          </div>
        ) : (
          <div className="notif-list">
            {notifications.map((n) => (
              <button
                className="notif"
                key={n.id}
                onClick={() => n.taskId && navigate(`/chat/${n.taskId}`)}
              >
                <span className={`notif-icon ${n.kind}`}>{ICONS[n.kind]}</span>
                <span className="notif-text">
                  <span className="notif-title">{n.title}</span>
                  <span className="notif-body">{n.body}</span>
                </span>
                <span className="notif-time">{formatRelative(n.ts)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
