import type { Athlete } from '../../lib/auth'
import type { Draft, SetDraft } from './settingsDraft'

const OPTIONS: Array<number | null> = [null, 2, 3, 4, 5, 6]

/** Auto (coach default) or 2–6 runs; the weekly total stays the same. */
export function RunsPerWeek({ draft, set, athlete, error }: { draft: Draft; set: SetDraft; athlete: Athlete; error?: string }) {
  const recommended = athlete.runs_per_week_recommended
  const ticked = Object.values(draft.available_days).filter(Boolean).length
  const chosen = draft.runs_per_week ?? recommended ?? null
  const capped = chosen != null && ticked > 0 && chosen > Math.min(ticked, 6)
  return (
    <div className="stack">
      <div className="card-head runs-head">
        <span className="field-label">Runs per week</span>
        {recommended != null && <span className="tag tag-plain">Coach recommends {recommended}</span>}
      </div>
      <div className="segmented segmented-full" role="radiogroup" aria-label="Runs per week">
        {OPTIONS.map((n) => (
          <button
            key={n ?? 'auto'}
            type="button"
            role="radio"
            aria-checked={draft.runs_per_week === n}
            className={`segmented-option ${draft.runs_per_week === n ? 'is-active' : ''}`}
            onClick={() => set('runs_per_week', n)}
          >
            {n ?? 'Auto'}
          </button>
        ))}
      </div>
      <p className="muted small">More runs = same total, shorter sessions. At least one rest day.</p>
      {draft.runs_per_week == null && recommended != null && <p className="small">Auto: the coach picks for your current volume — {recommended} runs a week now.</p>}
      {capped && <p className="small warn-text">You have {ticked} {ticked === 1 ? 'day' : 'days'} ticked, so the plan can use at most {Math.min(ticked, 6)}.</p>}
      {athlete.runs_per_week_effective != null && draft.runs_per_week != null && draft.runs_per_week === (athlete.runs_per_week ?? null) && (
        <p className="muted small">Planning with {athlete.runs_per_week_effective} runs a week now.</p>
      )}
      {error && <p className="field-error">{error}</p>}
    </div>
  )
}
