import { useState, type FormEvent } from 'react'
import { ApiError } from '../../lib/auth'
import { parseDate, todayISO } from '../../lib/format'
import { useDeleteRace, useRaces, useSaveRace } from '../../lib/queries'
import type { Race } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Field } from '../Field'
import { FlagIcon, PlusIcon } from '../Icons'
import { RacePlanSheet } from '../race/RacePlanSheet'
import { ErrorState, Skeleton } from '../States'

const DISTANCES = [
  { label: '5K', km: 5 },
  { label: '10K', km: 10 },
  { label: 'Half marathon', km: 21.1 },
  { label: 'Marathon', km: 42.2 },
]

type Draft = Omit<Race, 'id'> & { id?: number }
const blank = (): Draft => ({ name: '', date: '', distance_km: 10, is_target: false, notes: '', goal_time_s: null, start_time: null })

/** "1:58:00" / "52:30" → seconds; '' → null; junk → NaN. */
export function parseClock(text: string): number | null {
  const t = text.trim()
  if (!t) return null
  const parts = t.split(':').map((p) => Number(p))
  if (parts.some((n) => !Number.isFinite(n) || n < 0) || parts.length > 3) return Number.NaN
  return parts.reduce((acc, n) => acc * 60 + n, 0) * (parts.length === 1 ? 60 : 1)
}
export function clockText(s: number | null | undefined): string {
  if (s == null) return ''
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}

export function RacesCard() {
  const races = useRaces()
  const save = useSaveRace()
  const remove = useDeleteRace()
  const [editing, setEditing] = useState<Draft | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [goalText, setGoalText] = useState('')
  const [planFor, setPlanFor] = useState<number | null>(null)

  const open = (draft: Draft) => {
    setErrors({})
    save.reset()
    setGoalText(clockText(draft.goal_time_s))
    setEditing(draft)
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!editing) return
    const goal = parseClock(goalText)
    if (goal != null && (Number.isNaN(goal) || goal < 600)) {
      setErrors({ goal_time_s: 'Use h:mm:ss or mm:ss, e.g. 58:30 or 1:58:00.' })
      return
    }
    save.mutate({ ...editing, goal_time_s: goal }, {
      onSuccess: () => setEditing(null),
      onError: (caught) => setErrors(caught instanceof ApiError ? caught.fieldErrors() : { detail: 'Could not save.' }),
    })
  }

  const today = todayISO()
  const upcoming = races.data?.filter((r) => r.date >= today) ?? []
  const past = races.data?.filter((r) => r.date < today) ?? []

  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Races</h2>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => open(blank())}>
          <PlusIcon size={16} /> Add
        </button>
      </div>
      {races.isPending && <Skeleton lines={2} />}
      {races.isError && <ErrorState message="Races did not load." onRetry={() => races.refetch()} />}
      {races.data?.length === 0 && <p className="muted">No races yet. Add one and the coach builds towards it.</p>}
      <ul className="races">
        {[...upcoming, ...past].map((race) => (
          <li key={race.id} className="race-row">
            <button type="button" className={`race ${race.date < today ? 'is-past' : ''}`} onClick={() => open({ ...race })}>
              <span className="race-date">
                <span>{parseDate(race.date).toLocaleDateString(undefined, { month: 'short' })}</span>
                <strong>{parseDate(race.date).getDate()}</strong>
              </span>
              <span className="grow">
                <span className="race-name">
                  {race.name}
                  {race.is_target && <span className="badge">A race</span>}
                </span>
                <span className="muted small">
                  {race.distance_km} km · {parseDate(race.date).getFullYear()}
                  {race.goal_time_s ? ` · goal ${clockText(race.goal_time_s)}` : ''}
                </span>
              </span>
            </button>
            {race.date >= today && (
              <button type="button" className="btn btn-secondary btn-sm race-plan-btn" onClick={() => setPlanFor(race.id)}>
                <FlagIcon size={16} /> Race plan
              </button>
            )}
          </li>
        ))}
      </ul>

      <BottomSheet open={!!editing} onClose={() => setEditing(null)} title={editing?.id ? 'Edit race' : 'Add race'}>
        {editing && (
          <form className="stack" onSubmit={submit}>
            <Field label="Name" error={errors.name}>
              <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="Pune 10K" required />
            </Field>
            <div className="grid-2">
              <Field label="Date" error={errors.date}>
                <input type="date" value={editing.date} onChange={(e) => setEditing({ ...editing, date: e.target.value })} required />
              </Field>
              <Field label="Distance (km)" error={errors.distance_km}>
                <input
                  inputMode="decimal"
                  list="race-distances"
                  value={String(editing.distance_km)}
                  onChange={(e) => setEditing({ ...editing, distance_km: Number(e.target.value) || 0 })}
                />
                <datalist id="race-distances">
                  {DISTANCES.map((d) => <option key={d.km} value={d.km}>{d.label}</option>)}
                </datalist>
              </Field>
            </div>
            <div className="grid-2">
              <Field label="Goal time (optional)" hint="h:mm:ss or mm:ss" error={errors.goal_time_s}>
                <input inputMode="numeric" placeholder="58:30" value={goalText} onChange={(e) => setGoalText(e.target.value)} />
              </Field>
              <Field label="Start time" hint="For race morning" error={errors.start_time}>
                <input type="time" value={editing.start_time ?? ''} onChange={(e) => setEditing({ ...editing, start_time: e.target.value || null })} />
              </Field>
            </div>
            <div className="chips-row">
              {DISTANCES.map((d) => (
                <button
                  key={d.km}
                  type="button"
                  className={`pill-btn ${editing.distance_km === d.km ? 'is-active' : ''}`}
                  onClick={() => setEditing({ ...editing, distance_km: d.km })}
                >
                  {d.label}
                </button>
              ))}
            </div>
            <label className="switch-row">
              <span>
                <strong>A race</strong>
                <span className="muted small block">The one race the plan builds towards.</span>
                {errors.is_target && <span className="field-error">{errors.is_target}</span>}
              </span>
              <input
                type="checkbox"
                className="switch"
                checked={editing.is_target}
                onChange={(e) => setEditing({ ...editing, is_target: e.target.checked })}
              />
            </label>
            <Field label="Notes" error={errors.notes}>
              <textarea rows={2} value={editing.notes} onChange={(e) => setEditing({ ...editing, notes: e.target.value })} />
            </Field>
            {errors.detail && <p className="bad small">{errors.detail}</p>}
            <div className="row-end">
              {editing.id != null && (
                <button
                  type="button"
                  className="btn btn-danger btn-sm mr-auto"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(editing.id!, { onSuccess: () => setEditing(null) })}
                >
                  Delete
                </button>
              )}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
              <button className="btn btn-primary btn-sm" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
            </div>
          </form>
        )}
      </BottomSheet>
      <RacePlanSheet raceId={planFor} onClose={() => setPlanFor(null)} />
    </section>
  )
}
