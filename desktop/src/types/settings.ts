/** Memory categories, matching the backend's CHECK constraint. */
export const MEMORY_CATEGORIES = [
  "profile",
  "preference",
  "routine",
  "goal",
  "project",
  "person",
  "important_fact",
] as const;

export type MemoryCategory = (typeof MEMORY_CATEGORIES)[number];

/** Short labels for the UI; the backend stores the snake_case value. */
export const CATEGORY_LABEL: Record<MemoryCategory, string> = {
  profile: "Profile",
  preference: "Preference",
  routine: "Routine",
  goal: "Goal",
  project: "Project",
  person: "Person",
  important_fact: "Fact",
};

/** What the settings panel shows for one memory. Internal fields (key,
 *  confidence, source, id) stay in the service layer. */
export interface MemoryItem {
  id: string;
  category: MemoryCategory;
  content: string;
}

export const STYLE_LABEL: Record<string, string> = {
  balanced: "Balanced",
  concise: "Concise",
  detailed: "Detailed",
  friendly: "Friendly",
};

export const REMINDER_MINUTES_MIN = 1;
export const REMINDER_MINUTES_MAX = 120;

/** Ordinary settings, stored by the backend in SQLite. */
export interface AssistantSettings {
  assistantName: string;
  responseStyle: string;
  availableStyles: string[];
  /** EventKit identifier for new events; null means the macOS default. */
  defaultCalendarId: string | null;
  /** Minutes before an event that a reminder alerts. */
  reminderMinutes: number;
  /** Whether calendar reminders alert at all. */
  calendarNotifications: boolean;
  /** Whether the mascot appears when the cursor touches the bottom-right edge. */
  edgeActivation: boolean;
  /** Whether ordinary conversation is scanned for things worth remembering.
   *  Off stops new memories; existing ones stay and keep being used. */
  memoryEnabled: boolean;
}

export type SettingsPatch = Partial<
  Pick<
    AssistantSettings,
    | "assistantName"
    | "responseStyle"
    | "reminderMinutes"
    | "calendarNotifications"
    | "edgeActivation"
    | "memoryEnabled"
  >
> & {
  /** Empty string clears the choice and falls back to the macOS default. */
  defaultCalendarId?: string;
};
