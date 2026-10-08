import { useEffect, useMemo, useState } from 'react'
import { dur, monthDay, parseDate } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useWeekEdit, type WeekAction, type WeekEditBody, type WeekEditResult } from '../../lib/r16edit'
import type { CalWeek, Workout } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { Skeleton } from '../States'
import { NumStepper } from './Steppers'
import { HrRange, useHrBounds } from './Targets'
import '../../styles/r16edit.css'

const ACTIONS: Array<{ key: WeekAction; title: string; sub: string }> = [
  { key: 'add_minutes', title: 'Add minutes', sub: 'to each session' },
  { key: 'scale', title: 'Scale', sub: 'longer or shorter by %' },
  { key: 'add_walk_breaks', title: 'Walk breaks', sub: '1-min walks in runs' },
  { key: 'set_hr_range', title: 'Heart rate', sub: 'one range for runs' },
]

const kindName = (k: string) => k.toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const shortDay = (iso: string) => parseDate(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })

/**
 * R16 §A "Edit week" (Plan week header): one change applied to every matching future
 * session of the week, with a live dry-run preview of the affected days and warnings.
 */
export default function WeekEditSheet({
  week, workouts, open, onClose, onDone,
}: {
  week: CalWeek
  /** The week's sessions that can still be edited. */
  workouts: Workout[]
  open: boolean
  onClose: () => void
  onDone: (message: string) => void
}) {
  const bounds = useHrBounds()
  const [action, setAction] = useState<WeekAction>('add_minutes')
  const [minutes, setMinutes] = useState(5)
  const [pct, setPct] = useState(110)
  const [runMin, setRunMin] = useState(4)
  const [hr, setHr] = useState<[number, number]>(bounds.easy)
  const kindsKey = [...new Set(workouts.map((w) => w.kind).filter(Boolean))].join('|')
  const kindsAll = useMemo(() => (kindsKey ? kindsKey.split('|') : []), [kindsKey])
  const [kinds, setKinds] = useState<string[]>(kindsAll)
  useEffect(() => { setKinds(kindsAll) }, [kindsAll])
  const preview = useWeekEdit()
  const apply = useWeekEdit()

  const body = useMemo((): WeekEditBody | null => {
    if (!kinds.length) return null
    const value =
      action === 'add_minutes' ? minutes
        : action === 'scale' ? Math.round(pct) / 100
          : action === 'add_walk_breaks' ? runMin
            : { hr_low: hr[0], hr_high: hr[1] }
    if (action === 'add_minutes' && minutes === 0) return null
    if (action === 'scale' && pct === 100) return null
    return { week_start: week.start, action, value, ...(kinds.length < kindsAll.length ? { kinds } : {}) }
  }, [action, minutes, pct, runMin, hr, kinds, kindsAll.length, week.start])

  // Live preview (dry run), debounced while steppers are tapped.
  const key = JSON.stringify(body)
  useEffect(() => {
    if (!open || !body) return
    const t = setTimeout(() => preview.mutate({ ...body, dry_run: true }), 350)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, open])

  const result: WeekEditResult | undefined = body && preview.variables && JSON.stringify({ ...body, dry_run: true }) === JSON.stringify(preview.variables) ? preview.data : undefined
  const count = result?.changed.length ?? 0

  const run = () => {
    if (!body) return
    apply.mutate(body, {
      onSuccess: (r) => {
        const n = r.changed.length
        const w = r.watch
        const watch = w.updated ? ` · ${w.updated} updated on watch ✓` : w.pending ? ' · updating your watch…' : w.failed ? ' — watch not updated' : ''
        onDone(`${n} ${n === 1 ? 'session' : 'sessions'} updated${watch}`)
      },
    })
  }

  return (
    <BottomSheet open={open} onClose={onClose} title="Edit week" label="Edit week" full>
      <div className="ed">
        <p className="muted small ed-week-range">{monthDay(week.start)} – {monthDay(week.end)} · {workouts.length} {workouts.length === 1 ? 'session' : 'sessions'} left</p>

        <div className="ed-actions-grid" role="radiogroup" aria-label="What to change">
          {ACTIONS.map((a) => (
            <button key={a.key} type="button" role="radio" aria-checked={action === a.key} className={`ed-action ${action === a.key ? 'is-on' : ''}`} onClick={() => setAction(a.key)}>
              <b>{a.title}</b>
              <span>{a.sub}</span>
            </button>
          ))}
        </div>

        <div className="ed-panel">
          {action === 'add_minutes' && (
            <div className="ed-range-row">
              <span className="ed-range-lbl">Each session</span>
              <NumStepper label="Minutes per session" value={minutes} step={5} min={-60} max={60} format={(v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}`} unit="min" onChange={setMinutes} />
            </div>
          )}
          {action === 'scale' && (
            <div className="ed-range-row">
              <span className="ed-range-lbl">Length</span>
              <NumStepper label="Scale sessions" value={pct} step={5} min={50} max={150} format={(v) => `${v}%`} onChange={setPct} />
            </div>
          )}
          {action === 'add_walk_breaks' && (
            <div className="ed-range-row">
              <span className="ed-range-lbl">Walk 1 min every</span>
              <NumStepper label="Run minutes between walks" value={runMin} min={1} max={30} unit="min" onChange={setRunMin} />
            </div>
          )}
          {action === 'set_hr_range' && <HrRange low={hr[0]} high={hr[1]} bounds={bounds} onChange={(l, h) => setHr([l, h])} />}
        </div>

        {kindsAll.length > 1 && (
          <div className="stack-sm">
            <span className="ed-range-lbl">Which sessions</span>
            <div className="ed-kinds" role="group" aria-label="Which sessions">
              {kindsAll.map((k) => {
                const on = kinds.includes(k)
                return (
                  <button key={k} type="button" aria-pressed={on} className={`ed-kind ${on ? 'is-on' : ''}`} onClick={() => setKinds(on ? kinds.filter((x) => x !== k) : [...kinds, k])}>
                    {kindName(k)}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        <section className="ed-preview" aria-live="polite" aria-label="Preview">
          <span className="lbl">Preview</span>
          {!body && <p className="muted small">{kinds.length ? 'Pick a change to see the days it affects.' : 'Pick at least one kind of session.'}</p>}
          {body && !result && !preview.isError && <Skeleton lines={2} />}
          {preview.isError && <p className="bad small">{errorText(preview.error, 'Could not preview this change.')}</p>}
          {result && (
            <>
              {result.changed.length === 0 && <p className="muted small">No session this week would change.</p>}
              <ul className="ed-days">
                {result.changed.map((c) => {
                  const d = c.after.duration_s - c.before.duration_s
                  return (
                    <li key={c.workout_id}>
                      <span className="ed-day">{shortDay(c.date)}</span>
                      <span className="ed-day-title">{c.after.title || c.title}</span>
                      <span className="ed-day-dur">
                        {dur(c.before.duration_s)} → <b>{dur(c.after.duration_s)}</b>
                        {d !== 0 && <small className={d > 0 ? 'is-up' : 'is-down'}> {d > 0 ? '+' : '−'}{dur(Math.abs(d))}</small>}
                      </span>
                    </li>
                  )
                })}
                {result.skipped.map((s) => (
                  <li key={`s${s.workout_id}`} className="is-skipped">
                    <span className="ed-day">{shortDay(s.date)}</span>
                    <span className="ed-day-title">{s.title}</span>
                    <span className="ed-day-dur">{s.reason}</span>
                  </li>
                ))}
              </ul>
              {result.warnings.length > 0 && (
                <div className="ed-warnings">
                  <p className="ed-warnings-title">Harder than planned</p>
                  <ul>{result.warnings.map((w, i) => <li key={i}><b>{shortDay(w.date)}</b> · {w.text}</li>)}</ul>
                  <p className="ed-warnings-sub">You can still apply it — it’s your call.</p>
                </div>
              )}
            </>
          )}
        </section>

        <div className="ed-sticky">
          {apply.isError && <p className="bad small">{errorText(apply.error, 'Could not change the week.')}</p>}
          <div className="ed-foot">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="button" className="btn btn-primary btn-grow" disabled={!result || !count || apply.isPending} onClick={run}>
              {apply.isPending ? 'Applying…' : !count ? 'Apply' : `${result?.warnings.length ? 'Apply anyway' : 'Apply'} to ${count} ${count === 1 ? 'session' : 'sessions'}`}
            </button>
          </div>
        </div>
      </div>
    </BottomSheet>
  )
}
