/**
 * Putting your own session on a day.
 *
 * Rohit: "when I open that date it should have a chat box inside i will give
 * my description of run like 'i need to have a easy run basically in zone 2
 * for 30 min ie run/walk stratagy'".
 *
 * So the description box leads. It is the thing that reads a whole session off
 * one sentence, and the sentence is how people actually hold a session in
 * their head — "30 easy, run/walk" rather than a list of steps with heart-rate
 * bands on them. The presets underneath are for the days you do not want to
 * type: a shape and a length, built by the same code that writes the plan's
 * own sessions.
 *
 * Nothing saves on the first press. A described session is a guess at what you
 * meant, so it is built, shown with the coach's own line about what it
 * understood, and saved only when you say so — the same stance as every other
 * proposal in this app. The preset path previews too, because "40 minutes of
 * intervals" is also worth seeing before it is on your watch.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from '../../lib/auth'
import { errorText, invalidatePlanData } from '../../lib/queries'
import type { Workout } from '../../lib/types'
import { StepsList } from '../StepsList'
import { WorkoutBar } from '../WorkoutBar'

type Preset = { key: string; label: string }

type Options = {
  date: string
  writable: boolean
  reason: string | null
  has_run: boolean
  has_gym: boolean
  presets: Preset[]
  min_minutes: number
  max_minutes: number
  description_max: number
}

/** A change to a DIFFERENT day that the new session would need.
 *
 *  Rohit: "if you wanna change future runs ask for a updated on specific day i
 *  will give you a go or no go." So each one is its own question with its own
 *  answer — a list you accept wholesale is not consent to the item buried in
 *  the middle of it. Unticked means untouched. */
type Change = {
  workout_id: number
  date: string
  title: string
  current_minutes: number
  action: 'easier' | 'move' | 'skip'
  minutes: number | null
  move_to: string | null
  why: string
}

type Built = {
  type: 'run' | 'gym'
  understood: string
  changes?: Change[]
  session: {
    title: string
    duration_s: number
    steps?: Workout['steps']
    exercises?: { name: string; detail?: string }[]
    level?: number
  }
}

const MINUTES = [20, 30, 40, 60]

/** The example is Rohit's own sentence, because a placeholder that shows the
 *  shape of a good answer is worth more than one that says "describe it". */
const PLACEHOLDER = 'e.g. easy run in zone 2 for 30 min, run/walk strategy'

const dayName = (iso: string): string =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'long', day: 'numeric', month: 'short',
  })

/** What the change would do, in the words of the thing it does. */
function changeText(c: Change): string {
  if (c.action === 'skip') return `Drop it (${c.current_minutes}m)`
  if (c.action === 'move') return `Move it to ${c.move_to ? dayName(c.move_to) : 'another day'}`
  return `Shorten it: ${c.current_minutes}m \u2192 ${c.minutes}m`
}

export function AddSession({ date, onDone }: { date: string; onDone: () => void }) {
  const client = useQueryClient()
  const [text, setText] = useState('')
  const [preset, setPreset] = useState('RUN_WALK')
  const [minutes, setMinutes] = useState(30)
  const [built, setBuilt] = useState<Built | null>(null)
  const [open, setOpen] = useState(false)
  // Nothing is ticked to begin with. A proposal the athlete did not read must
  // not be one they accidentally agreed to, so the default for every other
  // day is "leave it alone".
  const [approved, setApproved] = useState<Set<number>>(new Set())

  const options = useQuery({
    queryKey: ['day-options', date],
    queryFn: () => api<Options>(`/days/${date}/`),
    enabled: open,
  })

  const preview = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<Built>(`/days/${date}/preview/`, { method: 'POST', ...json(body) }),
    onSuccess: setBuilt,
  })

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ type: string }>(`/days/${date}/create/`, { method: 'POST', ...json(body) }),
    onSuccess: () => {
      invalidatePlanData(client)
      client.invalidateQueries({ queryKey: ['strength'] })
      client.invalidateQueries({ queryKey: ['calendar-month'] })
      onDone()
    },
  })

  // What produced the preview is what gets saved. Keeping one body rather than
  // rebuilding it at save time means the thing on screen and the thing written
  // to the calendar cannot drift apart.
  const [lastBody, setLastBody] = useState<Record<string, unknown> | null>(null)
  const run = (body: Record<string, unknown>) => {
    setLastBody(body)
    setBuilt(null)
    setApproved(new Set())
    preview.mutate(body)
  }

  if (!open) {
    return (
      <button type="button" className="btn btn-secondary btn-grow add-open" onClick={() => setOpen(true)}>
        + Add a session
      </button>
    )
  }

  const o = options.data
  if (o && !o.writable) {
    return (
      <p className="small muted add-closed">
        {o.reason ?? 'That day cannot be changed.'}
      </p>
    )
  }

  const busy = preview.isPending || create.isPending

  return (
    <section className="add stack">
      <div className="row">
        <strong>Add a session</strong>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>

      <div className="add-field">
        <label className="field-label" htmlFor={`add-desc-${date}`}>Describe it</label>
        <textarea
          id={`add-desc-${date}`}
          rows={3}
          value={text}
          maxLength={o?.description_max ?? 500}
          placeholder={PLACEHOLDER}
          onChange={(e) => setText(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-primary btn-grow"
          disabled={busy || text.trim().length < 3}
          onClick={() => run({ type: 'run', description: text.trim() })}
        >
          {preview.isPending ? 'Reading that…' : 'Build it'}
        </button>
      </div>

      <details className="add-manual">
        <summary>Or pick a shape</summary>
        <div className="add-field">
          <div className="goal-pills">
            {(o?.presets ?? []).map((p) => (
              <button
                key={p.key}
                type="button"
                className={`goal-pill${preset === p.key ? ' is-on' : ''}`}
                onClick={() => setPreset(p.key)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="goal-pills">
            {MINUTES.map((m) => (
              <button
                key={m}
                type="button"
                className={`goal-pill${minutes === m ? ' is-on' : ''}`}
                onClick={() => setMinutes(m)}
              >
                {m} min
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-grow"
            disabled={busy}
            onClick={() => run({ type: 'run', preset, minutes })}
          >
            Build that run
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-grow"
            disabled={busy}
            onClick={() => run({ type: 'gym' })}
          >
            Add a gym session
          </button>
        </div>
      </details>

      {preview.error && (
        <p className="small bad" role="alert">
          {errorText(preview.error, 'That could not be built.')}
        </p>
      )}

      {built && (
        <div className="add-preview" aria-live="polite">
          {/* The coach's own line about what it took from the sentence. Shown
              above the session, because it is the thing to disagree with. */}
          {built.understood && <p className="add-understood">{built.understood}</p>}
          <p className="add-title">{built.session.title}</p>

          {built.type === 'run' && built.session.steps ? (
            <>
              <WorkoutBar steps={built.session.steps} height={56} />
              <StepsList steps={built.session.steps} />
            </>
          ) : (
            <ul className="add-moves">
              {(built.session.exercises ?? []).map((x, i) => (
                <li key={i}>{x.name}{x.detail ? <span className="muted"> · {x.detail}</span> : null}</li>
              ))}
            </ul>
          )}

          {/* Changes to OTHER days, each with its own yes. Shown between the
              session and the button that saves it, because they are part of
              what pressing it will do. */}
          {!!built.changes?.length && (
            <div className="add-changes">
              <p className="add-changes-head">
                This also needs a change on {built.changes.length === 1 ? 'another day' : 'other days'}.
                Say yes to each one, or leave it and nothing happens to it.
              </p>
              {built.changes.map((c) => (
                <label key={c.workout_id} className="add-change">
                  <input
                    type="checkbox"
                    checked={approved.has(c.workout_id)}
                    onChange={() =>
                      setApproved((was) => {
                        const next = new Set(was)
                        if (next.has(c.workout_id)) next.delete(c.workout_id)
                        else next.add(c.workout_id)
                        return next
                      })
                    }
                  />
                  <span>
                    <span className="add-change-day">{dayName(c.date)} · {c.title}</span>
                    <span className="add-change-do">{changeText(c)}</span>
                    <span className="add-change-why">{c.why}</span>
                  </span>
                </label>
              ))}
            </div>
          )}

          <button
            type="button"
            className="btn btn-primary btn-grow"
            disabled={busy || !lastBody}
            onClick={() => {
              if (!lastBody) return
              const picked = (built.changes ?? []).filter((c) => approved.has(c.workout_id))
              create.mutate({
                ...lastBody,
                approved_changes: picked.map((c) => ({
                  workout_id: c.workout_id,
                  action: c.action,
                  minutes: c.minutes,
                  move_to: c.move_to,
                })),
              })
            }}
          >
            {create.isPending
              ? 'Adding…'
              : approved.size
                ? `Add it, and change ${approved.size} other day${approved.size === 1 ? '' : 's'}`
                : 'Add it to this day'}
          </button>
          {create.error && (
            <p className="small bad" role="alert">
              {errorText(create.error, 'It could not be added.')}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
