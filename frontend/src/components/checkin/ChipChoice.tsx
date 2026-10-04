import { cap } from './checkinUtil'

/** A row of single-choice chips ("Legs: fresh / ok / heavy / sore"). */
export function ChipChoice<T extends string>({
  label, options, value, onChange,
}: { label: string; options: readonly T[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="ci-row">
      <span className="ci-label">{label}</span>
      <div className="ci-chips" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            className={`ci-chip ${value === option ? 'is-on' : ''}`}
            onClick={() => onChange(option)}
          >
            {cap(option)}
          </button>
        ))}
      </div>
    </div>
  )
}
