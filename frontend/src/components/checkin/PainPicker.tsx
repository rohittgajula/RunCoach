import { PAIN_AREAS, cap } from './checkinUtil'

export type PainState = { on: boolean; where: string; level: number }

/** "Any pain?" toggle → where (chips) + how bad (1–10). */
export function PainPicker({ value, onChange }: { value: PainState; onChange: (next: PainState) => void }) {
  return (
    <div className="ci-block">
      <div className="switch-row">
        <span className="ci-label">Any pain?</span>
        <button
          type="button"
          role="switch"
          aria-checked={value.on}
          aria-label="Any pain?"
          className={`switch ${value.on ? 'is-on is-bad' : ''}`}
          onClick={() => onChange({ ...value, on: !value.on })}
        />
      </div>
      {value.on && (
        <>
          <div className="ci-chips" role="radiogroup" aria-label="Where">
            {PAIN_AREAS.map((area) => (
              <button
                key={area}
                type="button"
                role="radio"
                aria-checked={value.where === area}
                className={`ci-chip ${value.where === area ? 'is-on' : ''}`}
                onClick={() => onChange({ ...value, where: area })}
              >
                {cap(area)}
              </button>
            ))}
          </div>
          <label className="ci-range">
            <span className="ci-range-head">
              <span>How bad</span>
              <b>{value.level}/10</b>
            </span>
            <input
              type="range" min={1} max={10} step={1} value={value.level}
              onChange={(e) => onChange({ ...value, level: Number(e.target.value) })}
            />
          </label>
        </>
      )}
    </div>
  )
}
