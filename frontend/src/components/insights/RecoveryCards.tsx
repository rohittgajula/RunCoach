import { dur, duration } from '../../lib/format'
import type { Insights } from '../../lib/types'
import { CHARTS, type ChartKey } from './charts'
import { InsightCard, Tile } from './Tile'

type Props = { data: Insights; onChart: (key: ChartKey) => void }

const HRV_STATUS: Record<string, { text: string; tone: string }> = {
  balanced: { text: 'Balanced', tone: 'tag-ok' },
  unbalanced: { text: 'Unbalanced', tone: 'tag-warn' },
  low: { text: 'Low', tone: 'tag-warn' },
  poor: { text: 'Poor', tone: 'tag-bad' },
}

const n = (v: number | null | undefined, digits = 0) => (v == null ? '--' : v.toFixed(digits))

export function RecoveryCard({ data, onChart }: Props) {
  const { hrv, resting_hr: rhr, sleep, body_battery: bb, stress } = data
  const status = hrv?.status ? HRV_STATUS[hrv.status] : null
  const pts = (key: ChartKey) => CHARTS[key].points(data)
  const trend = rhr?.trend_bpm_per_week
  return (
    <InsightCard title="Recovery" aside={status && <span className={`tag ${status.tone}`}>HRV {status.text}</span>}>
      <div className="tiles">
        <Tile
          label="HRV"
          value={n(hrv?.last_night_ms)}
          unit="ms"
          sub={
            hrv?.baseline_low != null && hrv.baseline_high != null
              ? `baseline ${Math.round(hrv.baseline_low)}–${Math.round(hrv.baseline_high)}`
              : hrv?.weekly_avg_ms != null ? `7-day avg ${n(hrv.weekly_avg_ms)}` : undefined
          }
          points={pts('hrv')}
          onClick={() => onChart('hrv')}
        />
        <Tile
          label="Resting HR"
          value={n(rhr?.current)}
          unit="bpm"
          sub={trend != null ? `${trend > 0 ? '+' : ''}${trend.toFixed(1)} bpm/week` : undefined}
          points={pts('rhr')}
          onClick={() => onChart('rhr')}
        />
        <Tile
          label="Sleep"
          value={sleep?.avg_s ? dur(sleep.avg_s) : '--'}
          sub={sleep?.avg_score != null ? `score ${Math.round(sleep.avg_score)}` : 'average'}
          points={pts('sleep')}
          onClick={() => onChart('sleep')}
        />
        <Tile label="Body Battery" value={n(bb?.avg)} sub="average" points={pts('body_battery')} onClick={() => onChart('body_battery')} />
        <Tile label="Stress" value={n(stress?.avg)} sub="average" points={pts('stress')} onClick={() => onChart('stress')} color="#d9861a" />
      </div>
    </InsightCard>
  )
}

export function BreathingCard({ data, onChart }: Props) {
  const r = data.respiration
  if (!r) return null
  return (
    <InsightCard title="Breathing">
      <div className="tiles">
        <Tile label="Asleep" value={n(r.sleep_avg_rpm, 1)} unit="brpm" points={CHARTS.respiration.points(data)} onClick={() => onChart('respiration')} />
        <Tile label="All day" value={n(r.avg_rpm, 1)} unit="brpm" onClick={() => onChart('respiration')} />
      </div>
    </InsightCard>
  )
}

export function FitnessCard({ data, onChart }: Props) {
  const { vo2max, race_predictions: race } = data
  if (!vo2max && !race) return null
  const rows: Array<[string, number | null | undefined]> = race
    ? [['5K', race['5k_s']], ['10K', race['10k_s']], ['Half', race.half_s], ['Marathon', race.marathon_s]]
    : []
  return (
    <InsightCard title="VO2max & race times">
      <div className="tiles">
        {vo2max && (
          <Tile label="VO2max" value={n(vo2max.value)} sub="ml/kg/min" points={CHARTS.vo2max.points(data)} onClick={() => onChart('vo2max')} />
        )}
        {race && (
          <div className="tile tile-static">
            <span className="tile-label">Garmin predicts</span>
            <dl className="kv kv-tight">
              {rows.filter(([, s]) => s).map(([label, s]) => (
                <div key={label}><dt>{label}</dt><dd>{duration(s)}</dd></div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </InsightCard>
  )
}
