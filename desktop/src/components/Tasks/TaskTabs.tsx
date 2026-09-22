import type { TaskTabId } from "../../types/tasks";

export interface TaskTabsProps {
  activeTab: TaskTabId;
  onChangeTab: (tab: TaskTabId) => void;
}

const TABS: { id: TaskTabId; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "upcoming", label: "Upcoming" },
  { id: "completed", label: "Completed" },
];

export function TaskTabs({ activeTab, onChangeTab }: TaskTabsProps) {
  return (
    <div className="task-tabs" role="tablist" aria-label="Tasks">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`task-tabs__button${activeTab === tab.id ? " task-tabs__button--active" : ""}`}
          onClick={() => onChangeTab(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
