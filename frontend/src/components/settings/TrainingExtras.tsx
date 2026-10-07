import { InfoButton } from '../health/InfoButton'
import { Toggle } from './HabitSettings'
import type { Draft, SetDraft } from './settingsDraft'

/** R13: auto-adjust, strength sessions per week (0–3 stepper) and the daily pain check. */
export function TrainingExtras({ draft, set, suggested = 2, errors }: { draft: Draft; set: SetDraft; suggested?: number; errors: Record<string, string> }) {
  const n = draft.strength_per_week
  return (
    <div className="stack">
      <Toggle
        label="Auto-adjust plan"
        hint="After each run, the next 1–2 sessions get easier when your body says so (high HR, hard effort, poor sleep, pain). You can undo every change."
        on={draft.auto_adjust_plan}
        onChange={(v) => set('auto_adjust_plan', v)}
      />
      {errors.auto_adjust_plan && <p className="field-error">{errors.auto_adjust_plan}</p>}

      <div className="stepper-row">
        <span className="grow">
          <strong>Strength sessions per week</strong>
          <InfoButton title="Strength sessions">
            <p>Short (20 min) sessions of calf, hip and core exercises from the Guides, placed on days without a run — never the day before a long or hard run.</p>
            <p>They get a little harder every two weeks. Two a week is plenty for most runners and cuts injury risk.</p>
          </InfoButton>
          <span className="muted small block">{n === 0 ? `Off · we suggest ${suggested}` : n === suggested ? 'Suggested amount' : `We suggest ${suggested}`}</span>
        </span>
        <div className="stepper" role="group" aria-label="Strength sessions per week">
          <button type="button" className="chip" aria-label="Fewer" disabled={n <= 0} onClick={() => set('strength_per_week', Math.max(0, n - 1))}>−</button>
          <span className="stepper-value" aria-live="polite">{n}</span>
          <button type="button" className="chip" aria-label="More" disabled={n >= 3} onClick={() => set('strength_per_week', Math.min(3, n + 1))}>+</button>
        </div>
      </div>
      {errors.strength_per_week && <p className="field-error">{errors.strength_per_week}</p>}

      <Toggle
        label="Daily “Anything hurting?”"
        hint="A one-tap pain check on Today. Pain on the same spot two days running makes the plan easier."
        on={draft.pain_daily_check}
        onChange={(v) => set('pain_daily_check', v)}
      />
    </div>
  )
}
