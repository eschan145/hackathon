import { useMemo, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { ChevronIcon, GearIcon, LayersIcon, MoreIcon, PlusIcon, SearchIcon } from "../lib/icons";
import { badgeFor, formatRelative, isRunning, useStore } from "../store";
import OrchestratrLogo from "./OrchestratrLogo";

export default function Sidebar() {
  const {
    tasks,
    approvals,
    chat,
    connected,
    setQuickAddOpen,
    titleFor,
    renameTask,
    restartTask,
    completeTask,
    deleteTask,
  } = useStore();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("orchestratr.sidebar.collapsed") === "true",
  );
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(10);
  const [menuTask, setMenuTask] = useState<string | null>(null);
  const attentionCount = tasks.filter(
    (task) => task.state === "AWAITING_APPROVAL" || Boolean(approvals[task.task_id]),
  ).length;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tasks;
    return tasks.filter((task) => {
      const messages = (chat[task.task_id] ?? []).map((message) => message.text).join(" ");
      return `${titleFor(task)} ${task.objective} ${messages}`.toLowerCase().includes(q);
    });
  }, [chat, query, tasks, titleFor]);

  const groups = useMemo(() => {
    const now = Date.now();
    const result: Array<{ label: string; tasks: typeof tasks }> = [
      { label: "Today", tasks: [] },
      { label: "Previous 7 days", tasks: [] },
      { label: "Older", tasks: [] },
    ];
    filtered.slice(0, visibleCount).forEach((task) => {
      const age = now - (task.created_at ?? 0) * 1000;
      if (age < 86400000) result[0].tasks.push(task);
      else if (age < 604800000) result[1].tasks.push(task);
      else result[2].tasks.push(task);
    });
    return result.filter((group) => group.tasks.length);
  }, [filtered, visibleCount]);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      localStorage.setItem("orchestratr.sidebar.collapsed", String(next));
      return next;
    });
  }

  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`} aria-label="Primary navigation">
      <div className="sidebar-brand">
        <OrchestratrLogo size={30} wordmark={!collapsed} />
        <button className="sidebar-collapse" onClick={toggleCollapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <ChevronIcon size={16} />
        </button>
      </div>

      <button className="sidebar-create" onClick={() => setQuickAddOpen(true)} title="New task (⌘K)">
        <PlusIcon size={18} />
        {!collapsed && <span>New task</span>}
      </button>

      <div className="sidebar-search">
        <SearchIcon size={17} />
        {!collapsed && (
          <input
            value={query}
            aria-label="Search tasks"
            placeholder="Search tasks"
            onChange={(event) => setQuery(event.target.value)}
          />
        )}
      </div>

      <nav className="sidebar-nav">
        <NavItem to="/now" icon={<LayersIcon />} label="Task Overview" collapsed={collapsed}>
          {attentionCount > 0 && <span className="rail-count">{attentionCount}</span>}
        </NavItem>
      </nav>

      {!collapsed && (
        <div className="sidebar-recents">
          <div className="sidebar-section-label">Recents</div>
          {filtered.length === 0 ? (
            <p className="sidebar-empty">No matching tasks</p>
          ) : (
            groups.map((group) => (
              <section key={group.label}>
                <h2>{group.label}</h2>
                {group.tasks.map((task) => {
                  const badge = badgeFor(task.state);
                  const hasApproval = Boolean(approvals[task.task_id]);
                  return (
                    <div className="recent-wrap" key={task.task_id}>
                      <button className="recent-task" onClick={() => navigate(`/task/${task.task_id}`)}>
                        <span className={`recent-status ${badge.tone}${isRunning(task.state) ? " live" : ""}${hasApproval ? " pulse" : ""}`} />
                        <span>
                          <strong title={titleFor(task)}>{titleFor(task)}</strong>
                          <small>{hasApproval ? "Needs approval" : task.created_at ? formatRelative(task.created_at * 1000) : badge.label}</small>
                        </span>
                      </button>
                      <button
                        className="recent-menu-button"
                        aria-label={`Actions for ${titleFor(task)}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setMenuTask(menuTask === task.task_id ? null : task.task_id);
                        }}
                      >
                        <MoreIcon size={17} />
                      </button>
                      {menuTask === task.task_id && (
                        <div className="recent-menu">
                          <button onClick={() => {
                            const value = window.prompt("Rename task", titleFor(task));
                            if (value !== null) renameTask(task.task_id, value);
                            setMenuTask(null);
                          }}>Rename</button>
                          <button onClick={async () => {
                            const id = await restartTask(task.task_id);
                            setMenuTask(null);
                            navigate(`/task/${id}`);
                          }}>Restart</button>
                          {task.state !== "COMPLETED" && <button onClick={() => completeTask(task.task_id)}>Mark complete</button>}
                          <button className="danger" onClick={() => {
                            if (window.confirm(`Delete “${titleFor(task)}”?`)) void deleteTask(task.task_id);
                            setMenuTask(null);
                          }}>Delete</button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </section>
            ))
          )}
          {filtered.length > visibleCount && (
            <button className="show-more" onClick={() => setVisibleCount((count) => count + 10)}>Show more</button>
          )}
        </div>
      )}

      <div className="sidebar-footer">
        <NavItem to="/settings" icon={<GearIcon />} label="Settings" collapsed={collapsed} />
        <div className="system-state" title={connected ? "Backend connected" : "Backend offline"}>
          <span className={`system-dot${connected ? " on" : ""}`} />
          {!collapsed && <span>{connected ? "Backend connected" : "Backend offline"}</span>}
        </div>
      </div>
    </aside>
  );
}

function NavItem({
  to,
  icon,
  label,
  collapsed,
  children,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  collapsed: boolean;
  children?: React.ReactNode;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
      title={label}
    >
      <span className="sidebar-item-icon">{icon}</span>
      {!collapsed && <span>{label}</span>}
      {children}
    </NavLink>
  );
}
