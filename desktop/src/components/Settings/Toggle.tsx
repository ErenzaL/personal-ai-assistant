export interface ToggleProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

/** A compact switch on a settings row. */
export function Toggle({ label, checked, onChange, disabled = false }: ToggleProps) {
  const className = ["settings-toggle", checked && "settings-toggle--on", disabled && "settings-toggle--disabled"]
    .filter(Boolean)
    .join(" ");
  return (
    <label className="settings-field">
      <span className="settings-field__label">{label}</span>
      <span className={className}>
        <input
          type="checkbox"
          role="switch"
          aria-checked={checked}
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="settings-toggle__knob" />
      </span>
    </label>
  );
}
