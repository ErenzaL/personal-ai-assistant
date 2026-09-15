import { useCallback, useEffect, useRef, useState } from "react";
import {
  describeApiError,
  forgetAllMemories,
  forgetMemory,
  listMemories,
  updateMemory,
  type MemoryDto,
} from "../services/api";
import type { MemoryCategory, MemoryItem } from "../types/settings";

function fromDto(dto: MemoryDto): MemoryItem {
  return { id: dto.id, category: dto.category as MemoryCategory, content: dto.content };
}

/**
 * Active personal memories, loaded from and written through the backend.
 * Every mutation goes to a deterministic endpoint and the list is updated
 * from the response, so the UI never shows a change the database refused.
 */
export function useMemories(enabled: boolean) {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      const rows = await listMemories();
      if (!mounted.current) return;
      setItems(rows.map(fromDto));
      setError(null);
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    } finally {
      if (mounted.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) void reload();
  }, [enabled, reload]);

  /** Runs an action, refreshes from the server, and reports failure. */
  const run = useCallback(
    async (action: () => Promise<unknown>): Promise<boolean> => {
      try {
        await action();
        await reload();
        return true;
      } catch (err) {
        if (mounted.current) setError(describeApiError(err));
        return false;
      }
    },
    [reload],
  );

  // No `add`: memories are learned automatically from conversation now
  // (see `memory_extraction.py`), not typed in here. Review, edit, forget.
  const edit = useCallback((id: string, content: string) => run(() => updateMemory(id, content)), [run]);
  const forget = useCallback((id: string) => run(() => forgetMemory(id)), [run]);
  const forgetAll = useCallback(() => run(() => forgetAllMemories()), [run]);

  return { items, isLoading, error, edit, forget, forgetAll, reload };
}
