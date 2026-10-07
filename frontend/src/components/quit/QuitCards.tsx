import { useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../lib/AuthContext'
import { ApiError } from '../../lib/auth'
import { parseDate } from '../../lib/format'
import { useCravingSummary, triggerLabel, type CravingSummary, type Savings } from '../../lib/r13'
import { Field } from '../Field'
import { EditIcon, PiggyIcon } from '../Icons'
import { CardHead, Meter, ToneChip } from '../Kit'
import { InfoButton } from '../health/InfoButton'
import { CravingButton } from './CravingButton'

const rupees = (v: number) => `₹${Math.round(v).toLocaleString('en-IN')}`
const hourText = (h: number) => `${((h + 11) % 12) + 1} ${h < 12 ? 'am' : 'pm'}`

/** R13 §8 craving patterns: % resisted, trend, top triggers, peak hours, places. */
export function CravingPatternsCard({ range }: { range: string }) {
  const q = useCravingSummary(range)
  const s = q.data
  if (q.data === null) return null
  return (
    <section className="card stack-sm craving-card">
      <CardHead
        title="Cravings"
        sub={s && s.total > 0 ? `${s.total} logged in this range` : 'Log a craving when it hits — the pattern shows you what to plan for.'}
        aside={<CravingButton />}
      />
      {s && s.total > 0 && <CravingBody s={s} />}
    </section>
  )
}

function CravingBody({ s }: { s: CravingSummary }) {
  const maxT = Math.max(1, ...s.by_trigger.map((t) => t.count))
  const maxH = Math.max(1, ...s.by_hour.map((h) => h.count))
  const hours = Array.from({ length: 24 }, (_, h) => s.by_hour.find((x) => x.hour === h)?.count ?? 0)
  const dir = s.trend?.direction
  return (
    <>
      <div className="craving-stats">
        <div>
          <span className="lbl">Resisted <InfoButton k="cravings_resisted" /></span>
          <b>{s.resisted_pct != null ? `${s.resisted_pct}%` : '--'}</b>
          <span className="muted small">{s.resisted} of {s.total}</span>
        </div>
        <div>
          <span className="lbl">Trend</span>
          {s.trend && s.trend.change_pct != null ? (
            <ToneChip tone={dir === 'down' ? 'good' : dir === 'up' ? 'bad' : 'flat'}>
              {dir === 'down' ? '▼' : dir === 'up' ? '▲' : '—'} {Math.abs(s.trend.change_pct)}% {dir === 'down' ? 'fewer' : dir === 'up' ? 'more' : ''}
            </ToneChip>
          ) : <span className="muted small">Need more weeks</span>}
          {s.trend && <span className="muted small">{s.trend.previous_period} → {s.trend.this_period}</span>}
        </div>
        {s.avg_intensity != null && (
          <div>
            <span className="lbl">Avg strength</span>
            <b>{s.avg_intensity.toFixed(1)}<small>/5</small></b>
          </div>
        )}
      </div>
      {s.by_trigger.length > 0 && (
        <div>
          <span className="lbl">Top triggers</span>
          <ul className="craving-bars">
            {s.by_trigger.slice(0, 5).map((t) => (
              <li key={t.trigger}>
                <span className="craving-bar-label">{t.label || triggerLabel(t.trigger)}</span>
                <span className="craving-bar"><span style={{ width: `${(t.count / maxT) * 100}%` }} /></span>
                <span className="craving-bar-n">{t.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <span className="lbl">When they hit</span>
        <div className="craving-hours" role="img" aria-label={`Most cravings around ${s.peak_hours.map((p) => hourText(p.hour)).join(', ')}`}>
          {hours.map((c, h) => (
            <span key={h} className={c ? 'has' : ''} style={{ height: `${c ? 12 + (c / maxH) * 44 : 4}px` }} />
          ))}
        </div>
        <div className="craving-hours-axis" aria-hidden="true"><span>12 am</span><span>6 am</span><span>12 pm</span><span>6 pm</span><span>11 pm</span></div>
        {s.peak_hours.length > 0 && (
          <p className="small">Peaks around <b>{s.peak_hours.map((p) => hourText(p.hour)).join(', ')}</b> — plan something for those moments (a walk, water, gum).</p>
        )}
      </div>
      {s.top_places.length > 0 && (
        <p className="small muted">Most often: {s.top_places.map((p) => `${p.place} (${p.count})`).join(' · ')}</p>
      )}
    </>
  )
}

/** R13 §8 savings goal: "New shoes ₹6,000" filled by money saved since the quit date. */
export function SavingsGoalCard() {
  const { athlete } = useAuth()
  const summary = useCravingSummary('4w')
  const [editing, setEditing] = useState(false)
  if (athlete?.smoke_goal !== 'quit') return null
  const goal = summary.data?.savings ?? null
  const hasGoal = !!athlete.savings_goal_name && !!athlete.savings_goal_amount
  return (
    <section className="card stack-sm savings-card">
      <CardHead
        title={<span className="savings-title"><PiggyIcon size={20} /> Saving for</span>}
        aside={hasGoal && !editing ? (
          <button type="button" className="icon-btn savings-edit" aria-label="Edit savings goal" onClick={() => setEditing(true)}><EditIcon size={18} /></button>
        ) : undefined}
      />
      {editing || !hasGoal ? (
        <SavingsForm onDone={() => setEditing(false)} canCancel={hasGoal} />
      ) : goal ? (
        <SavingsBody g={goal} />
      ) : (
        <p className="muted small">
          {athlete.cigarette_price ? 'Working it out…' : 'Add your price per cigarette in Settings → Habits to see money saved.'}
        </p>
      )}
    </section>
  )
}

function SavingsBody({ g }: { g: Savings }) {
  return (
    <>
      <div className="savings-head">
        <b className="savings-name">{g.name}</b>
        <span className="savings-amount">{rupees(g.saved)} <small>of {rupees(g.amount)}</small></span>
      </div>
      <Meter value={Math.min(g.saved, g.amount)} max={g.amount} topic="habits" label={`${g.pct}% of ${g.name}`} />
      <p className="small">
        {g.reached
          ? <>You’ve saved enough — treat yourself. 🎉</>
          : <>
              {rupees(g.remaining)} to go
              {g.eta ? <> · at {g.per_day != null ? `${rupees(g.per_day)}/day` : 'this rate'} you’ll get there around <b>{parseDate(g.eta).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</b></> : null}
            </>}
      </p>
      <p className="muted small">Money you’d have spent on cigarettes since your quit date.</p>
    </>
  )
}

function SavingsForm({ onDone, canCancel }: { onDone: () => void; canCancel: boolean }) {
  const { athlete, updateAthlete } = useAuth()
  const client = useQueryClient()
  const [name, setName] = useState(athlete?.savings_goal_name ?? '')
  const [amount, setAmount] = useState(athlete?.savings_goal_amount ? String(athlete.savings_goal_amount) : '')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    const n = Number(amount)
    if (!name.trim() || !Number.isFinite(n) || n < 1) {
      setErrors({ detail: 'Give it a name and a price.' })
      return
    }
    setBusy(true)
    setErrors({})
    try {
      await updateAthlete({ savings_goal_name: name.trim().slice(0, 60), savings_goal_amount: Math.round(n) })
      client.invalidateQueries({ queryKey: ['craving-summary'] })
      onDone()
    } catch (caught) {
      setErrors(caught instanceof ApiError ? caught.fieldErrors() : { detail: 'Could not save.' })
    } finally {
      setBusy(false)
    }
  }
  const clear = async () => {
    setBusy(true)
    try {
      await updateAthlete({ savings_goal_name: '', savings_goal_amount: null })
      client.invalidateQueries({ queryKey: ['craving-summary'] })
      onDone()
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="stack-sm" onSubmit={save}>
      <p className="muted small">Pick something you want. The money you’re not spending on cigarettes fills it up.</p>
      <div className="grid-2">
        <Field label="What" error={errors.savings_goal_name}>
          <input value={name} maxLength={60} placeholder="New shoes" onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Price (₹)" error={errors.savings_goal_amount}>
          <input inputMode="numeric" value={amount} placeholder="6000" onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ''))} />
        </Field>
      </div>
      {errors.detail && <p className="bad small">{errors.detail}</p>}
      <div className="row-end">
        {canCancel && <button type="button" className="btn btn-danger btn-sm mr-auto" disabled={busy} onClick={clear}>Remove</button>}
        {canCancel && <button type="button" className="btn btn-ghost btn-sm" onClick={onDone}>Cancel</button>}
        <button className="btn btn-primary btn-sm" disabled={busy}>{busy ? 'Saving…' : 'Save goal'}</button>
      </div>
    </form>
  )
}
