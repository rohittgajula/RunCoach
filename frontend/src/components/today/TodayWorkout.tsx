import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { dur, km, parseDate } from '../../lib/format'
import { useActivePlan } from '../../lib/queries'
import type { ActivityCard, CalDay, Step, Workout } from '../../lib/types'
import { ActivityCardView } from '../Cards'
import { ActivitySheet, WorkoutSheet } from '../DetailSheets'
import { CheckIcon } from '../Icons'
import { Skeleton } from '../States'
import { clock, groupSteps } from '../StepsList'
import { useCoachLaunch } from '../useCoachLaunch'
import { GarminSendButton } from '../workout/GarminSendButton'
import { BUILD_PLAN_PROMPT } from '../../lib/prompts'
import { AdjustedChip } from '../adjust/AdjustedChip'
import { StrengthCard } from '../strength/StrengthCard'

const KIND: Record<string, string> = {
  warmup: 'warm-up', run: 'run', walk: 'walk', stride: 'stride', recovery: 'recovery', cooldown: 'cool-down', interval: 'interval',
}
const isHard = (s: Step) => s.kind === 'run' || s.kind === 'interval' || s.kind === 'stride'

/** "3 × (3:00 run · 1:00 walk)" for the middle of the step bar. */
function coreText(steps: Step[]): string {
  const core = steps.filter((s) => s.kind !== 'warmup' && s.kind !== 'cooldown')
  const rows = groupSteps(core)
  if (!rows.length) return ''
  const one = (s: Step) => `${clock(s.duration_s)} ${KIND[s.kind] ?? s.kind}`
  const text = rows.slice(0, 2).map((r) =>
    r.type === 'pair'
      ? `${r.count > 1 ? `${r.count} × ` : ''}(${one(r.a)} · ${one(r.b)})`
      : `${r.count > 1 ? `${r.count} × ` : ''}${one(r.step)}`)
  return text.join(' + ') + (rows.length > 2 ? ' …' : '')
}

/** Heart-rate target from the run steps ("HR 130–145"), else the easy-day cap. */
function hrText(w: Workout): string {
  const runs = w.steps.filter((s) => isHard(s) && (s.hr_min || s.hr_max))
  const lo = Math.min(...runs.map((s) => s.hr_min ?? Infinity))
  const hi = Math.max(...runs.map((s) => s.hr_max ?? -Infinity))
  if (Number.isFinite(lo) && Number.isFinite(hi)) return `HR ${lo}–${hi}`
  if (Number.isFinite(hi)) return `HR ≤ ${hi}`
  if (w.guard?.hr_max) return `HR ≤ ${w.guard.hr_max}`
  return ''
}

/** Step bar: one block per step, width ∝ time, run blocks in full Running blue. */
export function StepStrip({ steps }: { steps: Step[] }) {
  const usable = steps.filter((s) => s.duration_s > 0)
  if (!usable.length) return null
  const first = usable[0]
  const last = usable[usable.length - 1]
  return (
    <div className="step-strip-wrap">
      <div className="step-strip" role="img" aria-label={`Steps: ${usable.map((s) => `${KIND[s.kind] ?? s.kind} ${dur(s.duration_s)}`).join(', ')}`}>
        {usable.map((s, i) => (
          <span key={i} className={isHard(s) ? 'is-run' : ''} style={{ flexGrow: Math.max(s.duration_s, 20) }} />
        ))}
      </div>
      <div className="step-strip-labels">
        <span>{first.kind === 'warmup' ? 'Warm-up' : ''}</span>
        <span className="step-strip-core">{coreText(usable)}</span>
        <span>{last.kind === 'cooldown' && usable.length > 1 ? 'Cool' : ''}</span>
      </div>
    </div>
  )
}

/** "Week 3 of 12" from the active plan's dates. */
function useWeekOfPlan(date: string): string {
  const plan = useActivePlan().data
  if (!plan) return ''
  const day = 86_400_000
  const start = parseDate(plan.start).getTime()
  const total = Math.max(1, Math.ceil((parseDate(plan.end).getTime() - start + day) / (7 * day)))
  const n = Math.floor((parseDate(date).getTime() - start) / (7 * day)) + 1
  return n >= 1 && n <= total ? `Week ${n} of ${total}` : ''
}

/** Today's workout hero (Running blue), rest-day card, or today's runs. */
export function TodayWorkout({ day, loading }: { day: CalDay | undefined; loading: boolean }) {
  const navigate = useNavigate()
  const launch = useCoachLaunch()
  const plan = useActivePlan()
  const [openWorkout, setOpenWorkout] = useState<Workout | null>(null)
  const [openActivity, setOpenActivity] = useState<ActivityCard | null>(null)
  const weekText = useWeekOfPlan(day?.date ?? '')

  if (loading && !day) return <section className="card"><Skeleton height={150} /></section>

  const workouts = (day?.items ?? []).flatMap((i) => (i.type === 'workout' ? [i.workout] : []))
  const activities = (day?.items ?? []).flatMap((i) => (i.type === 'activity' ? [i.activity] : []))
  const strength = (day?.items ?? []).flatMap((i) => (i.type === 'strength' ? [i.strength] : []))
  const linked = new Set(workouts.map((w) => w.completed_activity_id).filter(Boolean))

  return (
    <>
      {plan.data === null && (
        <section className="card banner">
          <p className="banner-title">No plan yet — ask the coach to build one</p>
          <p className="muted small">Tell it your race or goal. It asks only what it can't work out from your Garmin data.</p>
          <button type="button" className="btn btn-primary" onClick={() => navigate('/chat/new', { state: { prompt: BUILD_PLAN_PROMPT } })}>
            Ask the coach
          </button>
        </section>
      )}

      {workouts.map((w) => {
        const done = w.status === 'completed'
        const hr = hrText(w)
        return (
          <section key={w.id} className={`card hero-card ${w.status === 'skipped' ? 'is-skipped' : ''}`} aria-label="Today's workout">
            <button type="button" className="hero-top" onClick={() => setOpenWorkout(w)}>
              <span className="hero-eyebrow">
                Today's run{weekText ? ` · ${weekText}` : w.phase ? ` · ${w.phase.name}` : ''}
                {(w.adjusted_by === 'checkin' || w.adjusted_by === 'auto') && w.status === 'planned' && <span className="hero-tag">Adjusted</span>}
              </span>
              <span className="hero-title">{w.title} · {dur(w.duration_s)}</span>
              <span className="hero-stats">
                {done && w.actual?.distance_m ? <span>{km(w.actual.distance_m)}</span> : null}
                {hr && <span>{hr}</span>}
                {w.target_zone && <span>{w.target_zone}</span>}
                {!hr && !w.target_zone && <span>Load {Math.round(w.load)}</span>}
              </span>
            </button>
            <div className="hero-body">
              {w.auto_adjustment && w.status === 'planned' && <AdjustedChip adjustment={w.auto_adjustment} />}
              <StepStrip steps={w.steps} />
              <div className="hero-actions">
                {done ? (
                  <p className="hero-done"><span className="garmin-check"><CheckIcon size={14} /></span> Done</p>
                ) : w.status === 'planned' ? (
                  <GarminSendButton workout={w} compact />
                ) : (
                  <p className="hero-done muted">Skipped</p>
                )}
                <button type="button" className="btn btn-secondary" onClick={() => setOpenWorkout(w)}>Details</button>
                {w.status === 'planned' && (
                  <button type="button" className="btn btn-ghost hero-guide" onClick={() => launch.guide(w)}>Ask the coach how</button>
                )}
              </div>
            </div>
          </section>
        )
      })}

      {strength.map((s) => <StrengthCard key={s.id} session={s} />)}

      {day && !workouts.length && !activities.length && !strength.length && plan.data && (
        <section className="card rest-card">
          <span className="lbl">Today</span>
          <p className="rest-title">{day.rest ?? 'Rest'}</p>
          <p className="muted small">Nothing planned — an easy 20-minute walk keeps you moving.</p>
        </section>
      )}

      {activities.filter((a) => !linked.has(a.id)).map((a) => (
        <ActivityCardView key={a.id} activity={a} onOpen={() => setOpenActivity(a)} onReview={() => launch.review(a)} />
      ))}

      <WorkoutSheet workout={openWorkout} onClose={() => setOpenWorkout(null)} />
      <ActivitySheet activity={openActivity} onClose={() => setOpenActivity(null)} />
    </>
  )
}
