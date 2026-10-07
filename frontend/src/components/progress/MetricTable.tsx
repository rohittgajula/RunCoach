import type { ProgressMetric } from '../../lib/types'
import { fmtDelta, fmtValue, unitLabel } from './progressUtil'

function Arrow({ m }: { m: ProgressMetric }) {
  if (m.delta == null || m.delta === 0) return <span className="pm-arrow is-flat" aria-label="no change">–</span>
  const tone = m.better === true ? 'is-better' : m.better === false ? 'is-worse' : 'is-neutral'
  const word = m.better === true ? 'better' : m.better === false ? 'worse' : 'changed'
  return (
    <span className={`pm-arrow ${tone}`} aria-label={word}>
      {m.delta > 0 ? '▲' : '▼'}
    </span>
  )
}

/** Current vs previous with direction-aware colour (lower pace = green). */
export function MetricTable({ metrics, limit }: { metrics: ProgressMetric[]; limit?: number }) {
  const rows = limit ? metrics.slice(0, limit) : metrics
  if (!rows.length) return <p className="muted small">Not enough runs to compare yet.</p>
  return (
    <div className="table-wrap">
      <table className="pm-table">
        <thead>
          <tr><th>Metric</th><th>Now</th><th>Before</th><th>Change</th></tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.key}>
              <td>
                {m.label.replace(/\s*\(.*\)$/, '')}
                {unitLabel(m.unit) && <span className="pm-unit"> {unitLabel(m.unit)}</span>}
              </td>
              <td className="pm-num">{fmtValue(m.current, m.unit, true)}</td>
              <td className="pm-num muted">{fmtValue(m.previous, m.unit, true)}</td>
              <td className={`pm-num pm-delta ${m.better === true ? 'is-better' : m.better === false ? 'is-worse' : ''}`}>
                <Arrow m={m} /> {fmtDelta(m, true)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
