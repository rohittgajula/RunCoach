import type { HabitImpact, HabitKind } from '../../lib/types'
import { habitMeta } from './habitUtil'

const METRICS: Record<string, { name: string; unit: string }> = {
  hrv: { name: 'Overnight HRV', unit: 'ms' },
  rhr: { name: 'Resting HR', unit: 'bpm' },
  sleep_score: { name: 'Sleep score', unit: '' },
  body_battery: { name: 'Body Battery high', unit: '' },
  stress: { name: 'Average stress', unit: '' },
  sleep_respiration: { name: 'Sleep breathing rate', unit: 'brpm' },
  easy_hr: { name: 'HR on easy runs', unit: 'bpm' },
  efficiency: { name: 'Efficiency', unit: 'm/min/bpm' },
  hr_drift: { name: 'HR drift', unit: '%' },
}
const unitOf = (i: HabitImpact) => i.unit ?? METRICS[i.metric]?.unit ?? ''
const nameOf = (i: HabitImpact) => METRICS[i.metric]?.name ?? i.metric.replace(/_/g, ' ')

const AFTER: Record<HabitKind, string> = { smoke: 'smoking', alcohol: 'drinking', sugar: 'sugary food', private: 'it', caffeine: 'late caffeine' }

const num = (v: number | null, unit: string) => {
  if (v == null) return '--'
  const digits = Number.isInteger(v) ? 0 : Math.abs(v) < 1 ? 2 : 1
  return `${v.toFixed(digits)}${unit ? ` ${unit}` : ''}`
}

function ImpactCard({ impact }: { impact: HabitImpact }) {
  const unit = unitOf(impact)
  const tone = impact.direction === 'worse' ? 'is-worse' : impact.direction === 'better' ? 'is-better' : 'is-same'
  return (
    <li className={`impact ${tone}`}>
      <div className="impact-head">
        <span aria-hidden="true">{habitMeta(impact.habit).emoji}</span>
        <span className="impact-label">{nameOf(impact)}{impact.dose ? ` · ${impact.dose} drinks` : ''}</span>
        <span className={`tag ${impact.direction === 'worse' ? 'tag-bad' : impact.direction === 'better' ? 'tag-ok' : ''}`}>
          {impact.direction === 'no_clear_difference' ? 'no clear difference' : impact.direction}
        </span>
      </div>
      {/* The server writes the association sentence ("… the morning after drinking was … lower on average"). */}
      <p className="impact-text">{impact.label}</p>
      <p className="muted small">
        After: {num(impact.with_avg, unit)} · other days: {num(impact.without_avg, unit)}
      </p>
    </li>
  )
}

/** Only rows with ≥ 5 nights in both groups; the rest become a "keep logging" line. */
export function ImpactCards({ impact: all, hidePrivate = false, title = true }: { impact: HabitImpact[]; hidePrivate?: boolean; title?: boolean }) {
  const impact = hidePrivate ? all.filter((i) => i.habit !== 'private') : all
  const ready = impact.filter((i) => i.enough_data)
  const waiting = impact.filter((i) => !i.enough_data)
  // One "keep logging" hint per habit: how many nights each side has so far.
  const hints = new Map<HabitKind, { w: number; wo: number }>()
  for (const i of waiting) {
    if (ready.some((r) => r.habit === i.habit)) continue
    const h = hints.get(i.habit) ?? { w: 0, wo: 0 }
    hints.set(i.habit, { w: Math.max(h.w, i.n_with), wo: Math.max(h.wo, i.n_without) })
  }

  return (
    <div className="impact-wrap">
      {title && <h3 className="habit-sub">Impact</h3>}
      {ready.length > 0 && <ul className="impacts">{ready.map((i) => <ImpactCard key={`${i.habit}-${i.metric}-${i.dose ?? ''}`} impact={i} />)}</ul>}
      {[...hints].map(([habit, n]) => (
        <p key={habit} className="muted small">
          {habitMeta(habit).emoji} Keep logging — need 5 nights each after {AFTER[habit]} and without it to compare (so far {n.w} and {n.wo}).
        </p>
      ))}
      {!impact.length && <p className="muted small">Keep logging — once there are 5 nights each with and without a habit, you’ll see how your sleep, HRV and runs compare.</p>}
      {ready.length > 0 && <p className="muted small">These are averages from your own data, not proof of cause — other things change on those days too.</p>}
    </div>
  )
}
