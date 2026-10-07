import { useTrainingStatus } from '../../lib/queries'
import { CardHead, Pill, TargetBar } from '../Kit'

const GOOD = new Set(['productive', 'peaking', 'maintaining', 'recovery'])
const BAD = new Set(['unproductive', 'overreaching', 'strained', 'detraining'])
const STATE: Record<string, string> = { below: 'low', in_range: 'in range', above: 'high' }

/** Garmin training status + load focus (last 4 weeks vs target). Hidden without data. */
export function TrainingStatusCard() {
  const status = useTrainingStatus()
  const s = status.data
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
      {(items.length > 0 || s.load_focus?.feedback) && (
        <p className="chart-caption" style={{ marginTop: 8 }}>
          {items.length > 0 ? 'Light band = target range.' : ''}{s.load_focus?.feedback ? ` ${s.load_focus.feedback}.` : ''}
          {s.acwr != null ? ` Load ratio ${s.acwr.toFixed(2)}.` : ''}
        </p>
      )}
    </section>
  )
}
