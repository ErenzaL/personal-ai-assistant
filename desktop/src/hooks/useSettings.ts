import { useCallback, useEffect, useRef, useState } from "react";
import { describeApiError, getAssistantSettings, updateAssistantSettings } from "../services/api";
import type { AssistantSettings } from "../types/settings";
import { ASSISTANT_NAME } from "../stores/chatSeed";

const FALLBACK: AssistantSettings = {
  assistantName: ASSISTANT_NAME,
  responseStyle: "balanced",
  availableStyles: ["balanced", "concise", "detailed", "friendly"],
};

/** Assistant name and response style, persisted by the backend. */
export function useSettings() {
  const [settings, setSettings] = useState<AssistantSettings>(FALLBACK);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const dto = await getAssistantSettings();
        if (!mounted.current) return;
        setSettings({
          assistantName: dto.assistant_name,
          responseStyle: dto.response_style,
          availableStyles: dto.available_styles,
        });
      } catch {
        // Keep the defaults; the chat panel already reports backend trouble.
      }
    })();
    return () => {
      mounted.current = false;
    };
  }, []);

  const update = useCallback(async (patch: { assistantName?: string; responseStyle?: string }) => {
    try {
      const dto = await updateAssistantSettings({
        assistant_name: patch.assistantName,
        response_style: patch.responseStyle,
      });
      if (!mounted.current) return;
      setSettings({
        assistantName: dto.assistant_name,
        responseStyle: dto.response_style,
        availableStyles: dto.available_styles,
      });
      setError(null);
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    }
  }, []);

  return { settings, error, update };
}
