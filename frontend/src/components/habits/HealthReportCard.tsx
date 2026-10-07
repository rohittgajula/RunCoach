import { StatusPill } from '../Kit'
import type { HabitReport, HabitReportGarmin } from '../../lib/types'

const fmt = (v: number | null | undefined) => {
  if (v == null || !Number.isFinite(v)) return '--'
  const a = Math.abs(v)
  const digits = Number.isInteger(v) ? 0 : a < 10 ? 2 : a < 100 ? 1 : 0
  return v.toFixed(digits)
}

function Cell({ g }: { g: HabitReportGarmin }) {
  const tone = g.better === true ? 'is-better' : g.better === false ? 'is-worse' : 'is-neutral'
  const arrow = g.delta == null || g.delta === 0 ? '–' : g.delta > 0 ? '▲' : '▼'
  const word = g.better === true ? 'better' : g.better === false ? 'worse' : 'no clear change'
  return (
    <div className={`garmin-cell ${tone}`}>
      <span className="garmin-cell-label">{g.label}</span>
      <span className="garmin-cell-values">
        {g.before == null || g.now == null || !Number.isFinite(g.before) || !Number.isFinite(g.now) ? (
          <>
            {g.now != null && Number.isFinite(g.now) && <><strong>{fmt(g.now)}</strong>{g.unit && <small className="muted"> {g.unit}</small>} </>}
            <span className="muted-note">{g.now == null ? 'Not enough data yet' : 'nothing to compare yet'}</span>
          </>
        ) : (
          <>
            <span className="muted">{fmt(g.before)}</span>
            <span className="garmin-cell-to" aria-hidden="true">→</span>
            <strong>{fmt(g.now)}</strong>
            {g.unit && <small className="muted"> {g.unit}</small>}
          </>
        )}
      </span>
      {g.delta != null && Number.isFinite(g.delta) && (
        <span className="garmin-cell-delta" aria-label={word}>
          <span className="garmin-arrow">{arrow}</span> {`${g.delta > 0 ? '+' : g.delta < 0 ? '−' : ''}${fmt(Math.abs(g.delta))}`}
        </span>
      )}
    </div>
  )
}

/** "Has it improved or hurt me?" — overall verdict and the Garmin then → now grid. */
export function HealthReportCard({ report, rangeLabel }: { report: HabitReport | null | undefined; rangeLabel: string }) {
  if (!report) return null
  const overall = report.overall
  const garmin = report.garmin ?? []
  return (
    <section className="card insight health-report">
      <div className="card-head">
        <h2 className="card-title">Health report</h2>
        {overall?.status && <StatusPill status={overall.status} />}
      </div>
      {overall?.headline && <p className="report-headline">{overall.headline}</p>}
      {garmin.length > 0 ? (
        <>
          <p className="muted small">Last {rangeLabel} vs the {rangeLabel} before</p>
          <div className="garmin-grid">
            {garmin.map((g) => <Cell key={g.metric} g={g} />)}
          </div>
        </>
      ) : (
        <p className="muted small">No watch data to compare yet — sync Garmin for sleep, HRV and resting HR.</p>
      )}
    </section>
  )
}
