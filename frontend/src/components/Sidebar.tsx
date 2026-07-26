import { NavLink } from "react-router-dom";
import { BellIcon, CheckCircleIcon, GearIcon, LayersIcon, MessageIcon, PlusIcon } from "../lib/icons";
import { useStore } from "../store";

const MAX_CHATS = 6;

export default function Sidebar() {
  const { tasks, unreadCount, connected, setQuickAddOpen } = useStore();

  const chats = tasks.slice(0, MAX_CHATS);

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-mark">
          <LayersIcon size={16} />
        </span>
        <span className="brand-name">Assistant</span>
      </div>

      <button className="btn-primary quick-add" onClick={() => setQuickAddOpen(true)}>
        <PlusIcon size={15} />
        Quick Add Task
      </button>

      <nav className="sidebar-nav">
        <NavItem to="/tasks" icon={<CheckCircleIcon />} label="Tasks" />
        <NavItem to="/notifications" icon={<BellIcon />} label="Notifications">
          {unreadCount > 0 && <span className="nav-count">{unreadCount}</span>}
        </NavItem>
      </nav>

      <div className="sidebar-section">
        <span className="section-label">Task Chats</span>
        <div className="sidebar-nav">
          {chats.length === 0 ? (
            <span className="section-empty">No tasks yet</span>
          ) : (
            chats.map((t) => (
              <NavItem
                key={t.task_id}
                to={`/chat/${t.task_id}`}
                icon={<MessageIcon size={16} />}
                label={t.objective}
                subtle
              />
            ))
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <NavItem to="/settings" icon={<GearIcon />} label="Settings" />
        <div className="conn-row">
          <span className={`conn-dot${connected ? " on" : ""}`} />
          {connected ? "Backend connected" : "Backend offline"}
        </div>
      </div>
    </aside>
  );
}

function NavItem({
  to,
  icon,
  label,
  subtle,
  children,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  subtle?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <NavLink to={to} className={({ isActive }) => `nav-item${subtle ? " subtle" : ""}${isActive ? " active" : ""}`}>
      <span className="nav-icon">{icon}</span>
      <span className="nav-label" title={label}>
        {label}
      </span>
      {children}
    </NavLink>
  );
}
