import { useCallback, useEffect, useRef, useState } from "react";
import {
  describeApiError,
  getAssistantSettings,
  updateAssistantSettings,
  type AssistantSettingsDto,
} from "../services/api";
import { applyNativeSettings } from "../services/native";
import type { AssistantSettings, SettingsPatch } from "../types/settings";
import { ASSISTANT_NAME } from "../stores/chatSeed";

const FALLBACK: AssistantSettings = {
  assistantName: ASSISTANT_NAME,
  responseStyle: "balanced",
  availableStyles: ["balanced", "concise", "detailed", "friendly"],
  defaultCalendarId: null,
  reminderMinutes: 10,
  calendarNotifications: true,
  edgeActivation: true,
};

function fromDto(dto: AssistantSettingsDto): AssistantSettings {
  return {
    assistantName: dto.assistant_name,
    responseStyle: dto.response_style,
    availableStyles: dto.available_styles,
    defaultCalendarId: dto.default_calendar_id,
    reminderMinutes: dto.reminder_minutes,
    calendarNotifications: dto.calendar_notifications,
    edgeActivation: dto.edge_activation,
  };
}

/** The native side enforces three of these; hand them over whenever known. */
function pushNative(settings: AssistantSettings): void {
  void applyNativeSettings({
    edgeActivation: settings.edgeActivation,
    reminderMinutes: settings.reminderMinutes,
    calendarNotifications: settings.calendarNotifications,
  }).catch(() => undefined);
}

/** Ordinary settings, persisted by the backend in SQLite. */
export function useSettings() {
  const [settings, setSettings] = useState<AssistantSettings>(FALLBACK);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const next = fromDto(await getAssistantSettings());
        if (!mounted.current) return;
        setSettings(next);
        pushNative(next);
      } catch {
        // Keep the defaults; the chat panel already reports backend trouble.
      }
    })();
    return () => {
      mounted.current = false;
    };
  }, []);

  const update = useCallback(async (patch: SettingsPatch) => {
    try {
      const next = fromDto(
        await updateAssistantSettings({
          assistant_name: patch.assistantName,
          response_style: patch.responseStyle,
          default_calendar_id: patch.defaultCalendarId,
          reminder_minutes: patch.reminderMinutes,
          calendar_notifications: patch.calendarNotifications,
          edge_activation: patch.edgeActivation,
        }),
      );
      if (!mounted.current) return;
      setSettings(next);
      pushNative(next);
      setError(null);
    } catch (err) {
      if (mounted.current) setError(describeApiError(err));
    }
  }, []);

  return { settings, error, update };
}
