import { Link } from 'react-router-dom'
import { dayMonth } from '../../lib/format'
import { useWeeklyReport } from '../../lib/queries'
import { ChevronRight, ReportIcon } from '../Icons'

/** Mondays on Today: last week's report card in one glance, tap for the full report. */
export function WeeklyReportCard() {
  const monday = new Date().getDay() === 1
  const report = useWeeklyReport(null, monday)
  const r = report.data
  if (!monday || !r) return null
  return (
    <Link to={`/health/reports/${r.week_start}`} className="card link-row" aria-label="Last week's report">
      <span className="link-row-icon"><ReportIcon /></span>
      <span className="grow">
        <span className="link-row-title">Your week: {r.runs.done}{r.runs.planned ? ` of ${r.runs.planned}` : ''} runs · {r.runs.km.toFixed(1)} km</span>
        <span className="link-row-text">{dayMonth(r.week_start)} – {dayMonth(r.week_end)}{r.goal ? ` · This week: ${r.goal}` : ''}</span>
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}
