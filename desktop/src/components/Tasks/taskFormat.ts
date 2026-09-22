/** Short local-time phrasing for a due date, e.g. "Sunday · 11:59 PM",
 *  "Today · 6:00 PM", "Sep 3 · 9:00 AM". Mirrors the backend's own
 *  today/tomorrow/yesterday/weekday/short-date phrasing (`timeutil.format_local`). */
export function formatDueLabel(dueAt: string | null, now: Date = new Date()): string | null {
  if (!dueAt) return null;
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) return null;

  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const deltaDays = Math.round((startOfDay(due) - startOfDay(now)) / 86_400_000);
  const time = due.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

  let dayLabel: string;
  if (deltaDays === 0) dayLabel = "Today";
  else if (deltaDays === 1) dayLabel = "Tomorrow";
  else if (deltaDays === -1) dayLabel = "Yesterday";
  else if (deltaDays > 1 && deltaDays < 7) dayLabel = due.toLocaleDateString(undefined, { weekday: "long" });
  else dayLabel = due.toLocaleDateString(undefined, { month: "short", day: "numeric" });

  return `${dayLabel} · ${time}`;
}

/** Short date only (no time), e.g. "Sep 15", for a completion timestamp. */
export function formatCompletedLabel(completedAt: string | null): string | null {
  if (!completedAt) return null;
  const date = new Date(completedAt);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function isPastDue(dueAt: string | null, now: Date = new Date()): boolean {
  if (!dueAt) return false;
  const due = new Date(dueAt);
  return !Number.isNaN(due.getTime()) && due.getTime() < now.getTime();
}
