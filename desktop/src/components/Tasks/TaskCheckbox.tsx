export interface TaskCheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Accessible label -- the task or item's own text. */
  label: string;
  disabled?: boolean;
}

/**
 * A small square checkbox, distinct from Settings' on/off pill toggle: this
 * reads as a to-do checkmark (☐/☑), not a switch. Shared by task cards and
 * checklist items. `stopPropagation` on click so it never triggers a parent
 * card's expand/collapse toggle.
 */
export function TaskCheckbox({ checked, onChange, label, disabled = false }: TaskCheckboxProps) {
  return (
    <span
      className={`task-checkbox${checked ? " task-checkbox--checked" : ""}${disabled ? " task-checkbox--disabled" : ""}`}
      onClick={(event) => event.stopPropagation()}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.checked)}
      />
      <svg className="task-checkbox__mark" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M3.5 8.2l3 3 6-6.4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}
