import { dayMonth } from '../../lib/format'
import { useLungRecovery } from '../../lib/queries'
import type { LungMetric } from '../../lib/types'
import { CheckIcon, LungsIcon } from '../Icons'
import { Arrow, CardHead, Pill } from '../Kit'
import { Sparkline } from '../Sparkline'

const fmt = (m: LungMetric, v: number | null) => (v == null ? '—' : m.unit === '%' || m.key === 'sleep_breathing_rate' ? v.toFixed(1) : String(Math.round(v)))

/** Habits → lung recovery since the quit date (association, not cause). Needs a quit date. */
export function LungRecoveryCard({ enabled }: { enabled: boolean }) {
  const lung = useLungRecovery(enabled)
  const l = lung.data
  if (!enabled || !l || !l.available) return null
  return (
    <section className="card">
      <CardHead
        title={<span className="habit-card-title"><LungsIcon size={20} className="habit-icon" /> Lung recovery</span>}
        sub={l.quit_date ? `Since you quit on ${dayMonth(l.quit_date)} vs the 14 days before` : undefined}
        aside={l.days_since_quit != null ? <Pill topic="habits">Day {l.days_since_quit}</Pill> : undefined}
      />
      <div>
        {l.metrics.map((m) => (
          <div key={m.key} className="lung-metric">
            <div className="lung-row">
              <span>
                <b>{m.label}</b>
                {!m.enough_data && <span className="muted small"> · keep logging</span>}
              </span>
              <span className="num-strong">
                {fmt(m, m.before)} → {fmt(m, m.now)} {m.unit}{' '}
                {m.enough_data && m.change != null && (
                  <Arrow value={m.change} better={m.better == null ? null : (m.change > 0) === m.better ? 'higher' : 'lower'} />
                )}
              </span>
            </div>
            {m.series.length >= 3 && <Sparkline values={m.series.map((p) => p.value)} height={28} color="var(--habits)" />}
            {m.sentence && <p className="muted small">{m.sentence}</p>}
          </div>
        ))}
      </div>
      {l.milestones.length > 0 && (
        <ul className="milestones" style={{ marginTop: 12 }}>
          {l.milestones.map((ms) => (
            <li key={ms.label} className={`milestone ${ms.reached ? 'is-reached' : ''}`}>
              <span className="milestone-mark">{ms.reached && <CheckIcon size={12} />}</span>
              <span className="grow">{ms.label}</span>
              <span className="muted small">{dayMonth(ms.at.slice(0, 10))}</span>
            </li>
          ))}
        </ul>
      )}
      {l.note && <p className="chart-caption" style={{ marginTop: 8 }}>{l.note}</p>}
    </section>
  )
}
