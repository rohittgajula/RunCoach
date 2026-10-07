import { todayISO } from '../../lib/format'
import { Field } from '../Field'
import { Segmented } from './Segmented'
import type { Draft, SetDraft } from './settingsDraft'

const REDUCE = [
  { value: 'none' as const, label: 'Just track' },
  { value: 'reduce' as const, label: 'Reduce' },
]

/** Smoking goal + quit date + baseline + price; alcohol and sugar goals. */
export function HabitSettings({ draft, set, errors }: { draft: Draft; set: SetDraft; errors: Record<string, string> }) {
  return (
    <div className="stack">
      <Field label="Smoking" error={errors.smoke_goal}>
        <Segmented
          label="Smoking goal"
          value={draft.smoke_goal}
          onChange={(v) => set('smoke_goal', v)}
          options={[
            { value: 'quit', label: 'Quit' },
            { value: 'reduce', label: 'Reduce' },
            { value: 'none', label: 'No goal' },
          ]}
        />
      </Field>
      {draft.smoke_goal !== 'none' && (
        <div className="grid-2 grid-2-even">
          {draft.smoke_goal === 'quit' && (
            <Field label="Quit date" error={errors.smoke_quit_date}>
              <input type="date" max={todayISO()} value={draft.smoke_quit_date} onChange={(e) => set('smoke_quit_date', e.target.value)} />
            </Field>
          )}
          <Field label="Usual per day" hint="Before quitting / cutting down" error={errors.smoke_baseline_per_day}>
            <input inputMode="decimal" value={draft.smoke_baseline_per_day} onChange={(e) => set('smoke_baseline_per_day', e.target.value)} />
          </Field>
          <Field label="Price per cigarette (₹)" error={errors.cigarette_price}>
            <input inputMode="decimal" value={draft.cigarette_price} onChange={(e) => set('cigarette_price', e.target.value)} />
          </Field>
        </div>
      )}
      <Field label="Alcohol" error={errors.alcohol_goal}>
        <Segmented label="Alcohol goal" value={draft.alcohol_goal} onChange={(v) => set('alcohol_goal', v)} options={REDUCE} />
      </Field>
      <Field label="Sugar" error={errors.sugar_goal}>
        <Segmented label="Sugar goal" value={draft.sugar_goal} onChange={(v) => set('sugar_goal', v)} options={REDUCE} />
      </Field>
      <p className="muted small">
        Log with 🚬 🍺 🍫 on today’s card. Logs stay private — the coach only ever sees daily totals and averages.
      </p>
    </div>
  )
}
