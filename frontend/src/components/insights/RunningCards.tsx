import { pace } from '../../lib/format'
import type { Insights } from '../../lib/types'
import { ScoreRing } from '../ScoreRing'
import { CHARTS, parseTarget, type ChartKey } from './charts'
import { InsightCard, Tile } from './Tile'

type Props = { data: Insights; onChart: (key: ChartKey) => void }

export function ReadinessCard({ data }: { data: Insights }) {
  const r = data.readiness
  return (
    <InsightCard
      title="Readiness"
      aside={r && <span className="tag">{r.source === 'garmin' ? 'Garmin' : 'Computed'}</span>}
    >
      <div className="readiness">
        <ScoreRing score={r?.score ?? null} size={104} stroke={10} label="of 100" />
        <div className="grow">
          <p className="readiness-label">{r?.label || 'Not enough data'}</p>
          {r?.drivers.length ? (
            <ul className="drivers">{r.drivers.map((d, i) => <li key={i}>{d}</li>)}</ul>
          ) : (
            <p className="muted small">Sync sleep and HRV from Garmin to get a daily readiness score.</p>
          )}
        </div>
      </div>
    </InsightCard>
  )
}

/** Where on 120–190 spm the average sits, against the target band. */
function CadenceBand({ avg, target }: { avg: number | null; target: { low: number; high: number } | null }) {
  const lo = 120
  const hi = 190
  const at = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`
  return (
    <span className="cadence-band" aria-hidden="true">
      {target && <span className="cadence-target" style={{ left: at(target.low), width: `calc(${at(target.high)} - ${at(target.low)})` }} />}
      {avg != null && <span className="cadence-dot" style={{ left: at(avg) }} />}
    </span>
  )
}

export function RunningCard({ data, onChart }: Props) {
  const run = data.running
  if (!run) return null
  const pts = (key: ChartKey) => CHARTS[key].points(data)
  const last = (key: ChartKey) => {
    const values = pts(key).map((p) => p.value).filter((v): v is number => v != null)
    return values.length ? values[values.length - 1] : null
  }
  const fraction = last('run_fraction')
  const longest = last('longest_run')
  const easy = last('easy_pace')
  const target = parseTarget(run.cadence.target)
  return (
    <InsightCard title="How you’re running" aside={<span className="muted small">{run.runs} runs · {run.run_km.toFixed(1)} km</span>}>
      <div className="tiles">
        <Tile label="Running share" value={fraction != null ? `${Math.round(fraction)}` : '--'} unit="%" points={pts('run_fraction')} better={CHARTS.run_fraction.better} delta={CHARTS.run_fraction.delta ?? CHARTS.run_fraction.format} onClick={() => onChart('run_fraction')} />
        <Tile label="Longest run" value={longest != null ? CHARTS.longest_run.format(longest) : '--'} sub="continuous" points={pts('longest_run')} better={CHARTS.longest_run.better} delta={CHARTS.longest_run.delta ?? CHARTS.longest_run.format} onClick={() => onChart('longest_run')} />
        <Tile label="Easy pace" value={easy != null ? pace(easy) : '--'} unit="/km" sub="at zone 2 HR" points={pts('easy_pace')} reversed better={CHARTS.easy_pace.better} delta={CHARTS.easy_pace.delta ?? CHARTS.easy_pace.format} onClick={() => onChart('easy_pace')} />
        <Tile
          label="Cadence"
          value={run.cadence.avg != null ? String(Math.round(run.cadence.avg)) : '--'}
          unit="spm"
          sub={[
            target ? `target ${target.low}–${target.high}` : '',
            run.cadence.trend != null ? `${run.cadence.trend > 0 ? '+' : ''}${run.cadence.trend.toFixed(1)}/wk` : '',
          ].filter(Boolean).join(' · ') || undefined}
          better={CHARTS.cadence.better} delta={CHARTS.cadence.delta ?? CHARTS.cadence.format} onClick={() => onChart('cadence')}
        >
          <CadenceBand avg={run.cadence.avg} target={target} />
        </Tile>
      </div>
      {run.cadence.note && <p className="muted small insight-note">{run.cadence.note}</p>}
      {(run.hr_drift_avg != null || run.form) && (
        <dl className="kv">
          {run.hr_drift_avg != null && <div><dt>HR drift</dt><dd>{run.hr_drift_avg.toFixed(1)}%</dd></div>}
          {run.pace_cv_avg != null && <div><dt>Pace variation</dt><dd>{(run.pace_cv_avg * (run.pace_cv_avg <= 1 ? 100 : 1)).toFixed(0)}%</dd></div>}
          {run.form?.ground_contact_ms != null && <div><dt>Ground contact</dt><dd>{Math.round(run.form.ground_contact_ms)} ms</dd></div>}
          {run.form?.vertical_oscillation_cm != null && <div><dt>Vertical osc.</dt><dd>{run.form.vertical_oscillation_cm.toFixed(1)} cm</dd></div>}
          {run.form?.stride_length_m != null && <div><dt>Stride</dt><dd>{run.form.stride_length_m.toFixed(2)} m</dd></div>}
        </dl>
      )}
    </InsightCard>
  )
}
