import { useState } from 'react'
import { todayISO } from '../../lib/format'
import { errorText, useDeletePrivateLogs } from '../../lib/queries'
import { Field } from '../Field'
import { Segmented } from './Segmented'
import type { Draft, SetDraft } from './settingsDraft'

const REDUCE = [
  { value: 'none' as const, label: 'Just track' },
  { value: 'reduce' as const, label: 'Reduce' },
]

export function Toggle({ label, hint, on, onChange }: { label: string; hint?: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="switch-row">
      <span className="grow">
        <strong>{label}</strong>
        {hint && <span className="muted small block">{hint}</span>}
      </span>
      <button type="button" role="switch" aria-checked={on} aria-label={label} className={`switch ${on ? 'is-on' : ''}`} onClick={() => onChange(!on)} />
    </div>
  )
}

/** Smoking goal + quit date + baseline + price; alcohol and sugar goals; 🌙 Private. */
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

      <Toggle
        label="☕ Caffeine tile"
        hint="Adds ☕ to Log now, and a caffeine vs sleep card to Health → Habits."
        on={draft.caffeine_on_today}
        onChange={(v) => set('caffeine_on_today', v)}
      />

      <div className="private-settings">
        <Toggle
          label="🌙 Private habit"
          hint="Shown only as 🌙 Private. Never shown to the coach or in chat."
          on={draft.private_habit_enabled}
          onChange={(v) => set('private_habit_enabled', v)}
        />
        {errors.private_habit_enabled && <p className="field-error">{errors.private_habit_enabled}</p>}
        {draft.private_habit_enabled && (
          <>
            <Toggle label="Show on today card" on={draft.private_on_today} onChange={(v) => set('private_on_today', v)} />
            <Field label="Goal" error={errors.private_goal}>
              <Segmented label="🌙 Private goal" value={draft.private_goal} onChange={(v) => set('private_goal', v)} options={REDUCE} />
            </Field>
          </>
        )}
        <DeletePrivateLogs />
      </div>

      <p className="muted small">
        Log with 🚬 🍺 🍫 on today’s card. Logs stay private — the coach only ever sees daily totals and averages.
      </p>
    </div>
  )
}

/** Confirm in the page (no browser dialog), then DELETE /habits/logs/?kind=private. */
function DeletePrivateLogs() {
  const remove = useDeletePrivateLogs()
  const [confirming, setConfirming] = useState(false)
  if (remove.isSuccess && !confirming) {
    const n = remove.data?.deleted
    return <p className="muted small">🌙 Private logs deleted{n != null ? ` (${n})` : ''}.</p>
  }
  if (!confirming) {
    return (
      <button type="button" className="btn btn-danger btn-sm private-delete" onClick={() => setConfirming(true)}>
        Delete private logs
      </button>
    )
  }
  return (
    <div className="confirm-box" role="alertdialog" aria-label="Delete private logs">
      <p className="small">Delete every 🌙 Private log? This can’t be undone.</p>
      {remove.isError && <p className="bad small">{errorText(remove.error, 'Could not delete. Try again.')}</p>}
      <div className="row-end">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setConfirming(false)} disabled={remove.isPending}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-sm btn-confirm-danger"
          disabled={remove.isPending}
          onClick={() => remove.mutate(undefined, { onSuccess: () => setConfirming(false) })}
        >
          {remove.isPending ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </div>
  )
}
