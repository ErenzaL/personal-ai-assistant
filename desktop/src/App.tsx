import { useCallback, useState } from "react";
import { Avatar } from "./components/Avatar";
import { MascotStage } from "./components/MascotStage";
import { ChatWindow } from "./components/Chat";
import { ReminderPopup } from "./components/Reminder";
import { useReminders } from "./hooks/useReminders";
import { setChatOpen as setNativeChatOpen } from "./services/mascotWindow";
import mascot from "./assets/assistant.png";

function App() {
  // `?chat` in the URL opens the panel on load. Only useful when previewing the
  // UI in a plain browser via `npm run dev`; the Tauri window never sets it.
  const [chatOpen, setChatOpen] = useState(
    () => new URLSearchParams(window.location.search).has("chat"),
  );

  // Upcoming-event reminders: the native service decides when; this only shows them.
  const { reminder, bounce, snooze, dismiss } = useReminders();

  // Grow the native window first so the panel has room when it renders.
  const openChat = useCallback(async () => {
    await setNativeChatOpen(true);
    setChatOpen(true);
  }, []);

  // Unmount the panel first so nothing is clipped while the window shrinks.
  const closeChat = useCallback(async () => {
    setChatOpen(false);
    await setNativeChatOpen(false);
  }, []);

  return (
    <div className={chatOpen ? "app app--chat" : "app"}>
      {chatOpen && (
        <div className="app__chat">
          <ChatWindow onClose={closeChat} />
        </div>
      )}
      {reminder && (
        <div className="app__reminder">
          <ReminderPopup reminder={reminder} onSnooze={(m) => void snooze(m)} onDismiss={() => void dismiss()} />
        </div>
      )}
      <div className="app__mascot">
        <MascotStage>
          <Avatar
            src={mascot}
            alt="Assistant mascot"
            size={110}
            onClick={chatOpen ? closeChat : openChat}
            actionLabel={chatOpen ? "Close chat" : "Open chat"}
            bounce={bounce}
            badge={reminder !== null}
          />
        </MascotStage>
      </div>
    </div>
  );
}

export default App;
