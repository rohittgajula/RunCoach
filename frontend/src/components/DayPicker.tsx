const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Availability ("0" = Monday … "6" = Sunday) plus the long-run day. */
export function DayPicker({
  value, onChange, longRunDay, onLongRunDayChange,
}: {
  value: Record<string, boolean>
  onChange: (next: Record<string, boolean>) => void
  longRunDay: number
  onLongRunDayChange: (day: number) => void
}) {
  const selected = Object.values(value).filter(Boolean).length
  return (
    <div className="daypicker">
      <div className="daypicker-row">
        {DAYS.map((label, index) => {
          const key = String(index)
          const on = Boolean(value[key])
          return (
            <button
              key={key}
              type="button"
              className={`day ${on ? 'is-on' : ''}`}
              aria-pressed={on}
              onClick={() => {
                const next = { ...value, [key]: !on }
                onChange(next)
                // The API rejects a long-run day you are not available on — move it now.
                if (on && longRunDay === index) {
                  const fallback = Object.entries(next).find(([, v]) => v)?.[0]
                  if (fallback) onLongRunDayChange(Number(fallback))
                }
              }}
            >
              {label}
            </button>
          )
        })}
      </div>
      <p className="field-hint">
        {selected === 0 ? 'Pick at least one day you can train.' : `${selected} day${selected === 1 ? '' : 's'} a week.`}
      </p>
      <label className="field">
        <span className="field-label">Long run day</span>
        <select value={longRunDay} onChange={(event) => onLongRunDayChange(Number(event.target.value))}>
          {DAYS.map((label, index) =>
            value[String(index)] ? (
              <option key={index} value={index}>
                {label}
              </option>
            ) : null,
          )}
        </select>
      </label>
    </div>
  )
}
