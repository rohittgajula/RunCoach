import type { Range } from '../lib/types'

type Option<T extends string> = { value: T; label: string }

const OPTIONS: Array<Option<Range>> = [
  { value: '3m', label: '3 months' },
  { value: '6m', label: '6 months' },
  { value: '1y', label: '1 year' },
]

/** Segmented range picker. Defaults to 3m · 6m · 1y; Insights passes its own options. */
export function RangeSwitch<T extends string = Range>({
  value, onChange, options,
}: { value: T; onChange: (range: T) => void; options?: Array<Option<T>> }) {
  const list = options ?? (OPTIONS as unknown as Array<Option<T>>)
  return (
    <div className="segmented" role="tablist" aria-label="Range">
      {list.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          className={`segmented-option ${value === option.value ? 'is-active' : ''}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
