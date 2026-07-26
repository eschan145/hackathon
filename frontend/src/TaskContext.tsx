import React, { createContext, useContext, useState } from "react";

interface TaskContextValue {
  activeTaskId: string | null;
  setActiveTaskId: (id: string | null) => void;
}

const TaskContext = createContext<TaskContextValue | undefined>(undefined);

export function TaskProvider({ children }: { children: React.ReactNode }) {
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  return (
    <TaskContext.Provider value={{ activeTaskId, setActiveTaskId }}>{children}</TaskContext.Provider>
  );
}

export function useTaskContext(): TaskContextValue {
  const ctx = useContext(TaskContext);
  if (!ctx) throw new Error("useTaskContext must be used within TaskProvider");
  return ctx;
}
