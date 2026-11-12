/**
 * Which days you go to the gym, and what is in it.
 *
 * Both of these decide what the calendar shows, and neither had a control. The
 * model fields and the API have accepted them since the gym ladders went in;
 * nothing could write them, so every athlete got the automatic placement and
 * the most conservative equipment, forever.
 *
 * The days matter more than they look. A gym has opening hours and a commute,
 * and the best-spaced day of the week is no use on a day you cannot get there.
 * Leaving every day unticked is a real answer — it means "you choose", and the
 * placement rules spread the sessions around the running instead.
 *
 * The equipment is a ceiling rather than a mode: every rung 1 is bodyweight, so
 * somebody with a table and a chair starts exactly where somebody with a full
 * gym starts and simply stops climbing sooner. The consequence worth having is
 * that nothing can prescribe a goblet squat before you have said you own a
 * dumbbell.
 */

import { InfoButton } from '../health/InfoButton'
import type { Draft, SetDraft } from './settingsDraft'

const DAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
const FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const EQUIPMENT: { value: string; label: string; hint: string }[] = [
  { value: 'bodyweight', label: 'Bodyweight', hint: 'A wall, a chair and a sturdy table' },
  { value: 'dumbbells', label: 'Dumbbells', hint: 'Adds goblet squats, rows and RDLs' },
  { value: 'gym', label: 'Full gym', hint: 'Cables, machines, a bar' },
]

export function GymDays({ draft, set }: { draft: Draft; set: SetDraft }) {
  const days = draft.gym_days ?? {}
  const picked = Object.values(days).filter(Boolean).length
  const off = draft.strength_per_week === 0

  const toggle = (index: number) =>
    set('gym_days', { ...days, [String(index)]: !days[String(index)] })

  return (
    <div className="stack gym-days">
      <div className="row">
        <strong>Gym days</strong>
        <InfoButton title="Gym days">
          <p>
            Tick the days you can actually get to a gym. Leave them all unticked
            and the plan picks for you, spreading the sessions around your runs.
          </p>
          <p>
            A day you tick is still skipped when it falls the evening before your
            long run — heavy legs the night before is how a long run falls apart
            in the first ten minutes. That is the one case where the plan
            overrules you, and it loses to your own next run.
          </p>
        </InfoButton>
      </div>

      <div className="gym-row" role="group" aria-label="Gym days">
        {DAYS.map((label, index) => {
          const on = !!days[String(index)]
          return (
            <button
              key={index}
              type="button"
              className={`gym-day ${on ? 'is-on' : ''}`}
              aria-pressed={on}
              aria-label={FULL[index]}
              onClick={() => toggle(index)}
              disabled={off}
            >
              {label}
            </button>
          )
        })}
      </div>

      <p className="muted small">
        {off
          ? 'Set strength sessions per week above 0 to choose days.'
          : picked === 0
            ? 'None picked — the plan will place them around your runs.'
            : picked < draft.strength_per_week
              ? `${picked} day${picked === 1 ? '' : 's'} picked for ${draft.strength_per_week} sessions. Some weeks will have fewer.`
              : `${picked} day${picked === 1 ? '' : 's'} to choose from.`}
      </p>

      <div className="row" style={{ marginTop: 4 }}>
        <strong>What you have</strong>
        <InfoButton title="Equipment">
          <p>
            A ceiling, not a mode. Every exercise starts at a bodyweight version,
            so this does not change where you begin — it changes how far up each
            movement you can climb.
          </p>
          <p>
            On bodyweight only, pulling stops at a table row and squats at a
            bodyweight squat. Change it when you have had a look round the gym.
          </p>
        </InfoButton>
      </div>

      <div className="seg-row" role="group" aria-label="Available equipment">
        {EQUIPMENT.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`seg-btn ${draft.gym_equipment === option.value ? 'is-on' : ''}`}
            aria-pressed={draft.gym_equipment === option.value}
            onClick={() => set('gym_equipment', option.value)}
            disabled={off}
          >
            <span className="seg-label">{option.label}</span>
            <span className="seg-hint">{option.hint}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
