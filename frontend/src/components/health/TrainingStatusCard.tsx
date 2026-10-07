import { useTrainingStatus } from '../../lib/queries'
import { ChartFrame } from '../ChartFrame'
import { CardHead, Pill, TargetBar } from '../Kit'
import { MetricChart } from '../MetricChart'
import { bucket, periodCaption, withApiPeriod, type Period } from './healthRange'

const GOOD = new Set(['productive', 'peaking', 'maintaining', 'recovery'])
const BAD = new Set(['unproductive', 'overreaching', 'strained', 'detraining'])
const STATE: Record<string, string> = { below: 'low', in_range: 'in range', above: 'high' }

/** Garmin training status + load focus (last 4 weeks vs target). Hidden without data. */
export function TrainingStatusCard({ period: chosen }: { period?: Period }) {
  const status = useTrainingStatus(chosen?.params)
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
  return (
    <section className="card">
      <CardHead
        title="Training status"
        sub={items.length ? `Load focus, last ${s.load_focus?.period_days ?? 28} days vs target` : undefined}
        aside={s.status && (
          <Pill topic={GOOD.has(key) ? 'ok' : BAD.has(key) ? 'bad' : 'ink'} solid={GOOD.has(key) || BAD.has(key)}>{s.status}</Pill>
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
                label={`${i.label} ${Math.round(i.value)}${i.target_min != null && i.target_max != null ? `, target ${Math.round(i.target_min)}–${Math.round(i.target_max)}` : ''}`}
              />
            </div>
          ))}
        </div>
      )}
      {period && history.filter((h) => h.value != null).length >= 3 && (
        <ChartFrame title="Acute load" caption={periodCaption(period, { compare: false })}>
          <MetricChart data={history} height={140} freq={period.freq} color="var(--run)" />
        </ChartFrame>
      )}
      {(items.length > 0 || s.load_focus?.feedback) && (
        <p className="chart-caption" style={{ marginTop: 8 }}>
          {items.length > 0 ? 'Light band = target range.' : ''}{s.load_focus?.feedback ? ` ${s.load_focus.feedback}.` : ''}
          {s.acwr != null ? ` Load ratio ${s.acwr.toFixed(2)}.` : ''}
        </p>
      )}
    </section>
  )
}
