import { useState } from 'react'
import { dayMonth, todayISO } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { type Goal, type GoalBody, type GoalKind } from '../../lib/r14'
import { useAddGoalValue, useDeleteGoal, useGoals, useSaveGoal } from '../../lib/r14health'
import { BottomSheet } from '../BottomSheet'
import { Disclosure, SectionSummary } from '../Disclose'
import { Field } from '../Field'
import { PlusIcon } from '../Icons'
import { Meter, Pill } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

const KINDS: Array<{ kind: GoalKind; label: string; hint: string; unit: string }> = [
  { kind: 'race_time', label: 'Race time', hint: 'From Garmin’s race prediction', unit: '' },
  { kind: 'distance', label: 'Longest run', hint: 'Your longest single run since you set it', unit: 'km' },
  { kind: 'weekly_km', label: 'Weekly km', hint: 'Last 7 days of running', unit: 'km' },
  { kind: 'weight', label: 'Weight', hint: 'Your latest weigh-in', unit: 'kg' },
  { kind: 'smoke_free_days', label: 'Smoke-free days', hint: 'Your current streak', unit: 'days' },
  { kind: 'vo2max', label: 'VO2max', hint: 'Garmin’s latest estimate', unit: '' },
  { kind: 'resting_hr', label: 'Resting HR', hint: '7-day median', unit: 'bpm' },
  { kind: 'custom', label: 'Custom', hint: 'Anything — you log the numbers', unit: '' },
]
const DISTANCES = [5, 10, 21.1, 42.2]

/** "52:30" / "1:52:30" → seconds. */
function parseTime(text: string): number | null {
  const parts = text.trim().split(':').map((p) => Number(p))
  if (!parts.length || parts.some((p) => !Number.isFinite(p) || p < 0)) return null
  const s = parts.reduce((acc, p) => acc * 60 + p, 0)
  return parts.length >= 2 && s > 0 ? s : null
}
const timeText = (s: number) => {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}
const longDate = (iso: string) => new Date(`${iso}T00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

/** R14 §8 Health → More → Goals: progress bars, an estimated date and milestones. */
export function GoalsSection() {
  const goals = useGoals('all')
  const [editing, setEditing] = useState<Goal | 'new' | null>(null)
  const list = goals.data ?? []
  const active = list.filter((g) => g.status === 'active')
  const past = list.filter((g) => g.status !== 'active')

  if (goals.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (goals.isError) return <ErrorState message={errorText(goals.error, 'Goals did not load.')} onRetry={() => goals.refetch()} />
  if (goals.data === null) return <Empty title="Goals aren’t available yet">Check back after the next update.</Empty>

  return (
    <div className="stack">
      <SectionSummary
        title={active.length ? `${active.length} active ${active.length === 1 ? 'goal' : 'goals'}` : 'Set a long-term goal'}
        facts={[
          active.length ? 'Progress comes from your Garmin and logs — nothing to enter.' : 'A race time, a weight, a smoke-free streak…',
          'Dates are estimates from your recent trend.',
        ]}
      >
        <button type="button" className="btn btn-primary btn-sm" style={{ marginTop: 12 }} onClick={() => setEditing('new')}>
          <PlusIcon size={16} /> Add a goal
        </button>
      </SectionSummary>

      {active.map((g) => <GoalCard key={g.id} goal={g} onEdit={() => setEditing(g)} />)}

      {past.length > 0 && (
        <Disclosure id="goals-past" title="Past goals" sub={`${past.length} achieved or stopped`}>
          {past.map((g) => <GoalCard key={g.id} goal={g} onEdit={() => setEditing(g)} />)}
        </Disclosure>
      )}

      <GoalSheet goal={editing} onClose={() => setEditing(null)} />
    </div>
  )
}

function GoalCard({ goal: g, onEdit }: { goal: Goal; onEdit: () => void }) {
  const pct = Math.max(0, Math.min(100, g.progress_pct ?? 0))
  const p = g.projection
  return (
    <button type="button" className="card goal-card" onClick={onEdit} aria-label={`${g.title}: ${g.progress_pct ?? 0}%. Edit.`}>
      <div className="kit-head">
        <span className="grow kit-title">{g.title}</span>
        {g.status === 'achieved' ? <Pill topic="ok">Achieved</Pill> : g.status === 'abandoned' ? <Pill>Stopped</Pill> : g.progress_pct != null ? <b>{g.progress_pct}%</b> : null}
      </div>
      <p className="small">
        {g.display?.current ?? '—'} <span className="muted">→ {g.display?.target ?? g.target}</span>
        {g.target_date && <span className="muted"> by {longDate(g.target_date)}</span>}
      </p>
      <div className="goal-track">
        <Meter value={pct} max={100} topic="habits" label={`${g.title} progress`} />
        <div className="goal-milestones" aria-hidden="true">
          {g.milestones.map((m) => (
            <span key={m.pct} className={`goal-ms ${m.reached_on ? 'is-reached' : ''}`} style={{ left: `${m.pct}%` }} title={`${m.pct}%`} />
          ))}
        </div>
      </div>
      {g.status === 'active' && p && (
        <p className="muted small">
          {p.date ? <>Projected: <b>{longDate(p.date)}</b> <span className="pill">Estimate</span>{p.on_track != null && (p.on_track ? ' · on track' : ' · behind the target date')}</> : p.note}
        </p>
      )}
      {g.status === 'achieved' && g.achieved_on && <p className="muted small">Reached on {longDate(g.achieved_on)}</p>}
    </button>
  )
}

function GoalSheet({ goal, onClose }: { goal: Goal | 'new' | null; onClose: () => void }) {
  return (
    <BottomSheet open={goal != null} onClose={onClose} title={goal === 'new' ? 'New goal' : goal ? 'Edit goal' : ''}>
      {goal != null && <GoalForm key={goal === 'new' ? 'new' : goal.id} goal={goal === 'new' ? null : goal} onDone={onClose} />}
    </BottomSheet>
  )
}

function GoalForm({ goal, onDone }: { goal: Goal | null; onDone: () => void }) {
  const save = useSaveGoal()
  const del = useDeleteGoal()
  const addValue = useAddGoalValue()
  const [kind, setKind] = useState<GoalKind>((goal?.kind as GoalKind) ?? 'race_time')
  const [title, setTitle] = useState(goal?.title ?? '')
  const [distance, setDistance] = useState<number>(goal?.distance_km ?? 10)
  const [target, setTarget] = useState(goal ? (goal.kind === 'race_time' ? timeText(goal.target) : String(goal.target)) : '')
  const [date, setDate] = useState(goal?.target_date ?? '')
  const [unit, setUnit] = useState(goal?.unit ?? '')
  const [start, setStart] = useState('')
  const [value, setValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const meta = KINDS.find((k) => k.kind === kind) ?? KINDS[KINDS.length - 1]
  const targetNum = kind === 'race_time' ? parseTime(target) : Number(target)
  const ok = targetNum != null && Number.isFinite(targetNum) && targetNum > 0 && (goal || kind !== 'custom' || (unit.trim() && start.trim() !== ''))
  const error = save.error ?? del.error ?? addValue.error

  const submit = () => {
    if (!ok || targetNum == null) return
    const body: GoalBody = goal
      ? { title: title.trim() || undefined, target: targetNum, target_date: date || null }
      : {
          kind, target: targetNum, ...(date ? { target_date: date } : {}), ...(title.trim() ? { title: title.trim() } : {}),
          ...(kind === 'race_time' ? { distance_km: distance } : {}),
          ...(kind === 'custom' ? { unit: unit.trim(), start_value: Number(start) } : {}),
        }
    save.mutate({ id: goal?.id, body }, { onSuccess: onDone })
  }

  return (
    <div className="stack">
      {!goal && (
        <div className="ci-chips" role="radiogroup" aria-label="Kind of goal">
          {KINDS.map((k) => (
            <button key={k.kind} type="button" role="radio" aria-checked={kind === k.kind} className={`ci-chip ${kind === k.kind ? 'is-on' : ''}`} onClick={() => setKind(k.kind)}>
              {k.label}
            </button>
          ))}
        </div>
      )}
      <p className="muted small">{meta.hint}</p>
      {!goal && kind === 'race_time' && (
        <div className="ci-chips" role="radiogroup" aria-label="Race distance">
          {DISTANCES.map((d) => (
            <button key={d} type="button" role="radio" aria-checked={distance === d} className={`ci-chip ${distance === d ? 'is-on' : ''}`} onClick={() => setDistance(d)}>
              {d === 21.1 ? 'Half' : d === 42.2 ? 'Marathon' : `${d}K`}
            </button>
          ))}
        </div>
      )}
      <div className="grid-2">
        <Field label={kind === 'race_time' ? 'Target time (mm:ss)' : `Target${meta.unit || unit ? ` (${meta.unit || unit})` : ''}`}>
          <input inputMode={kind === 'race_time' ? 'text' : 'decimal'} value={target} placeholder={kind === 'race_time' ? '58:00' : ''} onChange={(e) => setTarget(e.target.value)} />
        </Field>
        <Field label="By (optional)">
          <input type="date" value={date} min={todayISO()} onChange={(e) => setDate(e.target.value)} />
        </Field>
      </div>
      {!goal && kind === 'custom' && (
        <div className="grid-2">
          <Field label="Unit"><input value={unit} maxLength={12} placeholder="push-ups" onChange={(e) => setUnit(e.target.value)} /></Field>
          <Field label="Where you are now"><input inputMode="decimal" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        </div>
      )}
      <Field label="Name (optional)">
        <input value={title} maxLength={80} placeholder="e.g. 10K under 58 minutes" onChange={(e) => setTitle(e.target.value)} />
      </Field>
      {error && <p className="bad small">{errorText(error, 'Could not save.')}</p>}
      <button type="button" className="btn btn-primary btn-block" disabled={!ok || save.isPending} onClick={submit}>
        {save.isPending ? 'Saving…' : goal ? 'Save' : 'Add goal'}
      </button>

      {goal?.kind === 'custom' && goal.status === 'active' && (
        <div className="row-wrap">
          <input inputMode="decimal" aria-label={`Today's value (${goal.unit})`} placeholder={`Today (${goal.unit})`} value={value} onChange={(e) => setValue(e.target.value)} style={{ flex: 1 }} />
          <button type="button" className="btn btn-secondary btn-sm" disabled={!value || addValue.isPending} onClick={() => addValue.mutate({ id: goal.id, value: Number(value) }, { onSuccess: () => setValue('') })}>
            Log value
          </button>
        </div>
      )}

      {goal && goal.series.length > 0 && (
        <p className="muted small">Started {dayMonth(goal.start_date)} at {goal.display?.start ?? goal.start_value ?? '—'} · {goal.milestones.filter((m) => m.reached_on).length} of 4 milestones reached</p>
      )}

      {goal && (
        <div className="row-wrap">
          {goal.status === 'active' ? (
            <button type="button" className="btn btn-secondary btn-sm" disabled={save.isPending} onClick={() => save.mutate({ id: goal.id, body: { status: 'abandoned' } }, { onSuccess: onDone })}>Stop this goal</button>
          ) : goal.status === 'abandoned' ? (
            <button type="button" className="btn btn-secondary btn-sm" disabled={save.isPending} onClick={() => save.mutate({ id: goal.id, body: { status: 'active' } }, { onSuccess: onDone })}>Restart</button>
          ) : null}
          {confirmDelete ? (
            <>
              <span className="small grow">Delete for good?</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmDelete(false)}>Cancel</button>
              <button type="button" className="btn btn-danger btn-sm" disabled={del.isPending} onClick={() => del.mutate(goal.id, { onSuccess: onDone })}>Delete</button>
            </>
          ) : (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConfirmDelete(true)}>Delete</button>
          )}
        </div>
      )}
    </div>
  )
}
