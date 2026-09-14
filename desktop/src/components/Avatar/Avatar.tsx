import "./Avatar.css";

export interface AvatarProps {
  /** Image URL. Pass any imported PNG to swap the mascot. */
  src: string;
  /** Accessible description of the image. */
  alt: string;
  /** Rendered width in CSS pixels. Height follows the image's aspect ratio. */
  size?: number;
  /** Called when the mascot is clicked. */
  onClick?: () => void;
  /** Accessible label for the click action, e.g. "Open chat". */
  actionLabel?: string;
}

/**
 * Static mascot image with a subtle hover lift, rendered as a button so it can
 * be clicked and reached by keyboard. Presentation only: no state, no
 * animation of body parts.
 */
export function Avatar({ src, alt, size = 180, onClick, actionLabel }: AvatarProps) {
  return (
    <button
      type="button"
      className="avatar"
      style={{ width: size }}
      onClick={onClick}
      aria-label={actionLabel ?? alt}
    >
      <img className="avatar__image" src={src} alt={alt} draggable={false} />
    </button>
  );
}
