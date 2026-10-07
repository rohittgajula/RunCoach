import { todayISO } from '../../lib/format'
import { useActivePlan, useTrainingStatus, useWeek } from '../../lib/queries'
import type { PhaseKind } from '../../lib/types'
import { ChartFrame } from '../ChartFrame'
import { CardHead, Pill, TargetBar } from '../Kit'
import { MetricChart } from '../MetricChart'
import { LOAD_FOCUS_MEANING, STATUS_MEANING } from './glossary'
import { bucket, periodCaption, withApiPeriod, type Period } from './healthRange'
import { InfoButton } from './InfoButton'

const GOOD = new Set(['productive', 'peaking', 'maintaining', 'recovery'])
const BAD = new Set(['unproductive', 'overreaching', 'strained', 'detraining'])
const STATE: Record<string, string> = { below: 'low', in_range: 'in range', above: 'high' }
const EASY_PHASES = new Set<PhaseKind>(['base', 'recovery', 'taper'])

/**
 * Where the plan is now: phase kind and whether this week is run/walk. Used only to
 * explain the load bars — safety rule: never suggest adding hard sessions.
 */
function usePlanContext() {
  const plan = useActivePlan()
  const week = useWeek(todayISO())
  const p = plan.data
  const phase = p?.phases?.find((ph) => ph.id === p.current_phase_id)
    ?? p?.phases?.find((ph) => ph.start <= todayISO() && ph.end >= todayISO())
    ?? null
  const runWalk = (week.data?.days ?? []).some((d) => d.items.some((i) =>
    i.type === 'workout' && i.workout.steps?.some((st) => st.kind === 'walk')))
  // Early = the first phase of the plan (or no plan yet).
  const early = !p || !phase || phase.order === Math.min(...(p.phases ?? []).map((ph) => ph.order))
  return { phase: phase?.kind ?? null, runWalk, early, hasPlan: !!p }
}

function meaningSentence(items: Array<{ key: string; state: string | null }>, ctx: ReturnType<typeof usePlanContext>, statusKey: string): string {
  const low = (k: string) => items.find((i) => i.key === k)?.state === 'below'
  const highOver = items.some((i) => i.state === 'above')
  if (statusKey === 'overreaching' || statusKey === 'strained') {
    return 'Your body needs more rest right now — keep every run easy and sleep well. The coach will ease the plan if needed.'
  }
  if (highOver) {
    return 'One kind of training is above Garmin’s range — keep easy days truly easy and let the plan set the pace of progress.'
  }
  if (low('high_aerobic') || low('anaerobic')) {
    if (ctx.runWalk || ctx.early || (ctx.phase && EASY_PHASES.has(ctx.phase)) || !ctx.hasPlan) {
      return `Your plan is mostly easy on purpose while you build up${ctx.runWalk ? ' with run/walk' : ''} — low high-aerobic and anaerobic load is expected right now. Nothing to fix.`
    }
    return 'Low hard-effort load is fine — the coach will add harder sessions when your plan gets there. Don’t add them yourself.'
  }
  if (low('low_aerobic')) return 'Easy running is the base everything else stands on — just keep doing your planned runs.'
  return 'Your training mix is inside Garmin’s recommended ranges. Keep following the plan.'
}

/** Garmin training status + load focus (last 4 weeks vs target), explained in plain words. */
export function TrainingStatusCard({ period: chosen }: { period?: Period }) {
  const status = useTrainingStatus(chosen?.params)
  const ctx = usePlanContext()
  const s = status.data
  // R12: with a period the history follows it (acute load per day/week/month).
  const period = chosen ? withApiPeriod(chosen, s?.period) : null
  const history = period && s?.history
    ? bucket(s.history.map((h) => ({ date: h.date, value: h.acute_load })), period.freq, 'mean')
    : []
  const items = s?.load_focus?.items ?? []
  if (!s || (!s.status && !items.length)) return null
  const key = s.status_key ?? ''
  const max = Math.max(1, ...items.map((i) => Math.max(i.value, i.target_max ?? 0))) * 1.1
  const days = s.load_focus?.period_days ?? 28
  const current = STATUS_MEANING.find((m) => m.key === key)
  return (
    <section className="card">
      <CardHead
        title="Training status"
        sub={current ? current.text : items.length ? `What kind of training you’ve done, last ${days} days` : undefined}
        aside={s.status && (
          <span className="title-info">
            <Pill topic={GOOD.has(key) ? 'ok' : BAD.has(key) ? 'bad' : 'ink'} solid={GOOD.has(key) || BAD.has(key)}>{s.status}</Pill>
            <InfoButton title="Training status" label="What do the training statuses mean?">
              <p>Garmin compares your recent training with how your fitness (VO2max) and recovery are moving.</p>
              <ul className="status-list">
                {STATUS_MEANING.filter((m) => m.key !== 'strained' || key === 'strained').map((m) => (
                  <li key={m.key} className={m.key === key ? 'is-current' : ''}>
                    <strong>{m.label}{m.key === key ? ' · you now' : ''}</strong>
                    <span>{m.text}</span>
                  </li>
                ))}
              </ul>
            </InfoButton>
          </span>
        )}
      />
      {items.length > 0 && (
        <div className="load-focus">
          {items.map((i) => (
            <div key={i.key} className="load-focus-row">
              <div>
                <span>{i.label}</span>
                <span className="num-strong">{Math.round(i.value)}{i.state ? ` · ${STATE[i.state] ?? i.state}` : ''}</span>
              </div>
              <TargetBar
                value={i.value}
                max={max}
                low={i.target_min}
                high={i.target_max}
                topic="run"
                label={`${i.label} ${Math.round(i.value)}${i.target_min != null && i.target_max != null ? `, recommended ${Math.round(i.target_min)}–${Math.round(i.target_max)}` : ''}`}
              />
              {LOAD_FOCUS_MEANING[i.key] && <p className="load-focus-meaning">{LOAD_FOCUS_MEANING[i.key]}</p>}
            </div>
          ))}
        </div>
      )}
      {items.length > 0 && (
        <>
          <p className="chart-caption" style={{ marginTop: 10 }}>
            Bar = your training load from the last {days === 28 ? '4 weeks' : `${days} days`}. Light band = Garmin’s recommended range. “Low” = less than recommended.
            {s.acwr != null ? ` Load ratio ${s.acwr.toFixed(2)} (last week vs your usual; 0.8–1.3 means a steady build).` : ''}
          </p>
          <p className="callout"><b>What this means for you:</b> {meaningSentence(items, ctx, key)}</p>
        </>
      )}
      {!items.length && s.load_focus?.feedback && <p className="chart-caption" style={{ marginTop: 8 }}>{s.load_focus.feedback}.</p>}
      {period && history.filter((h) => h.value != null).length >= 3 && (
        <ChartFrame title="Training load" info={<InfoButton k="acute_load" />} caption={periodCaption(period, { compare: false })}>
          <MetricChart data={history} height={140} freq={period.freq} color="var(--run)" />
        </ChartFrame>
      )}
    </section>
  )
}
