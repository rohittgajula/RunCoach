/**
 * One row of seven days, each of which is a run day, a gym day, or neither.
 *
 * Before this there were two independent pickers — "days you could run" and
 * "days you go to the gym" — plus a runs-per-week control and a
 * sessions-per-week control, four controls for one decision. Nothing stopped a
 * day being ticked in both, because in the data model it still can be, and
 * then the calendar showed a run and a gym session on the same date with no
 * way to tell which you had meant.
 *
 * The fix is here rather than in the model. `available_days` and `gym_days`
 * stay exactly as they are — the generator, the placement rules and the
 * calendar all read them unchanged — and this control simply never writes
 * `true` to both for the same day. One tap cycles run → gym → rest, so the
 * exclusion is a property of the thing you are touching instead of a
 * validation message after the fact.
 *
 * The number of gym days is the number you have chosen, so `strength_per_week`
 * follows the picker. Two controls that could disagree about the same fact is
 * one control too many.
 */

import { InfoButton } from '../health/InfoButton'
import type { Draft, SetDraft } from './settingsDraft'

const SHORT = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
const FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

type Kind = 'run' | 'gym' | 'rest'
const NEXT: Record<Kind, Kind> = { run: 'gym', gym: 'rest', rest: 'run' }
const WORD: Record<Kind, string> = { run: 'Run', gym: 'Gym', rest: 'Rest' }

function RunGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="td-glyph">
      <circle cx="14.6" cy="4.3" r="2.15" fill="currentColor" />
      <path d="M12.7 8.2 9.2 10.4l-1.5 4M12.7 8.2l3.2 1.3 1.1 3 2.6 1.1M12.7 8.2l-1.1 5 3 2.6-.7 5.2M11.6 13.2l-3.5 2.9-3.1-.4"
        fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function GymGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="td-glyph">
      <path d="M3.6 9.4v5.2M6.8 7.2v9.6M17.2 7.2v9.6M20.4 9.4v5.2M6.8 12h10.4"
        fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" />
    </svg>
  )
}

const kindOf = (draft: Draft, index: number): Kind => {
  const key = String(index)
  if (draft.gym_days?.[key]) return 'gym'
  if (draft.available_days?.[key]) return 'run'
  return 'rest'
}

export function TrainingDays({ draft, set }: { draft: Draft; set: SetDraft }) {
  const kinds = SHORT.map((_, i) => kindOf(draft, i))
  const runDays = kinds.filter((k) => k === 'run').length
  const gymDays = kinds.filter((k) => k === 'gym').length
  const restDays = kinds.filter((k) => k === 'rest').length

  const cycle = (index: number) => {
    const key = String(index)
    const next = NEXT[kindOf(draft, index)]
    // Written together so the two maps can never both say yes for one day.
    set('available_days', { ...draft.available_days, [key]: next === 'run' })
    set('gym_days', { ...draft.gym_days, [key]: next === 'gym' })
    if (next === 'gym' || kindOf(draft, index) === 'gym') {
      const after = SHORT.map((_, i) =>
        i === index ? next : kindOf(draft, i)).filter((k) => k === 'gym').length
      set('strength_per_week', after)
    }
    // The long run has to stay on a day you actually run.
    if (next !== 'run' && draft.long_run_day === index) {
      const fallback = SHORT.findIndex((_, i) => i !== index && kindOf(draft, i) === 'run')
      if (fallback >= 0) set('long_run_day', fallback)
    }
  }

  // A gym day the evening before the long run is the one collision the plan
  // overrules, so it is worth saying here rather than after the fact.
  const longRun = draft.long_run_day
  const eve = (longRun + 6) % 7
  const clash = kinds[longRun] === 'run' && kinds[eve] === 'gym'

  return (
    <div className="stack">
      <div className="row">
        <strong>Your week</strong>
        <InfoButton title="Training days">
          <p>
            Tap a day to cycle it: run, gym, rest. A day is one or the other —
            picking gym on a run day moves it, rather than stacking two sessions
            on one date.
          </p>
          <p>
            Rest is a choice, not a leftover. It is where last week turns into
            this week&rsquo;s capacity, and the plan will not fill it in behind
            your back.
          </p>
        </InfoButton>
      </div>

      <div className="td-row" role="group" aria-label="Training days">
        {SHORT.map((label, index) => {
          const kind = kinds[index]
          return (
            <button
              key={index}
              type="button"
              className="td-day"
              data-kind={kind}
              aria-label={`${FULL[index]}: ${WORD[kind]}. Tap to change.`}
              onClick={() => cycle(index)}
            >
              <span className="td-dow">{label}</span>
              {kind === 'run' ? <RunGlyph /> : kind === 'gym' ? <GymGlyph /> : <span className="td-dot" />}
              <span className="td-word">{WORD[kind]}</span>
            </button>
          )
        })}
      </div>

      <p className="muted small td-count">
        <b>{runDays}</b> run {runDays === 1 ? 'day' : 'days'} ·{' '}
        <b>{gymDays}</b> gym · <b>{restDays}</b> rest
      </p>

      {runDays > 0 && (
        <label className="field td-long">
          <span className="field-label">Long run on</span>
          <select
            value={draft.long_run_day}
            onChange={(e) => set('long_run_day', Number(e.target.value))}
          >
            {SHORT.map((_, index) =>
              kinds[index] === 'run' ? (
                <option key={index} value={index}>{FULL[index]}</option>
              ) : null,
            )}
          </select>
        </label>
      )}

      {runDays === 0 && (
        <p className="small warn-text">
          No run days picked. The plan has nowhere to put a run.
        </p>
      )}
      {restDays === 0 && (
        <p className="small warn-text">
          Every day is a session. At least one rest day is how the training
          actually lands.
        </p>
      )}
      {/* Two controls can name the same number: the days picked here, and the
          "strength sessions per week" stepper below. They are not redundant —
          three days picked for two sessions means "any two of these" — but
          asking for more sessions than there are days silently gives you
          fewer, and the app should say so rather than quietly disagree with
          itself. This line used to live on the old gym-days picker and went
          when that picker did. */}
      {gymDays > 0 && draft.strength_per_week > gymDays && (
        <p className="small warn-text">
          {draft.strength_per_week} gym sessions a week asked for, but only{' '}
          {gymDays} gym {gymDays === 1 ? 'day' : 'days'} picked — you will get{' '}
          {gymDays} a week.
        </p>
      )}
      {clash && (
        <p className="small warn-text">
          {FULL[eve]} is a gym day the evening before your long run. The plan
          will move it — heavy legs the night before is how a long run falls
          apart in the first ten minutes.
        </p>
      )}
    </div>
  )
}
