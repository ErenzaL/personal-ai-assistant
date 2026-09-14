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

export interface AssistantSettings {
  assistantName: string;
  responseStyle: string;
  availableStyles: string[];
}
