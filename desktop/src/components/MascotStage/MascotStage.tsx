import type { ReactNode } from "react";
import "./MascotStage.css";

export interface MascotStageProps {
  /** The avatar (or any element) to stand on the platform. */
  children: ReactNode;
}

/**
 * Translucent platform the mascot stands on. The platform is shorter than the
 * mascot, so the character rises above its top edge.
 */
export function MascotStage({ children }: MascotStageProps) {
  return (
    <div className="mascot-stage" data-tauri-drag-region>
      <div className="mascot-stage__platform" data-tauri-drag-region />
      <div className="mascot-stage__actor">{children}</div>
    </div>
  );
}
