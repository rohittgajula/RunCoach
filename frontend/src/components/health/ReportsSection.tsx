import { Link, NavLink, useLocation, useParams } from 'react-router-dom'
import { dateTime, dayMonth, dur } from '../../lib/format'
import { errorText, useWeeklyReport, useWeeklyReportAi, useWeeklyReports } from '../../lib/queries'
import type { WeeklyReport } from '../../lib/types'
import { Bullets } from '../Bullets'
import { ChevronRight, SparkIcon } from '../Icons'
import { CardHead, ThenNow, type ThenNowRow } from '../Kit'
import { Markdown } from '../Markdown'
import { Empty, ErrorState, Skeleton } from '../States'
import { ShareButton } from '../share/ShareButton'
import { InfoButton } from './InfoButton'
import { MonthlyReportsSection } from './MonthlyReport'

const ZONE_COLOR: Record<string, string> = {
  below: 'var(--walk)', Z1: 'var(--run-soft)', Z2: 'var(--easy-2)', Z3: 'var(--run)', Z4: 'var(--fuel)', Z5: 'var(--bad)',
}

const fmtNum = (v: number | null | undefined, unit: string) => {
  if (v == null) return '—'
  if (unit === 's' || unit === 'h:mm') return dur(v)
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

/** R13 §11: Weekly | Monthly tabs above the reports. */
export function ReportTabs() {
  const { pathname } = useLocation()
  const weekly = !pathname.includes('/reports/monthly')
  return (
    <nav className="segmented segmented-full report-tabs" aria-label="Report period">
      <NavLink to="/health/reports" end className={`segmented-option ${weekly ? 'is-active' : ''}`} aria-current={weekly ? 'page' : undefined}>Weekly</NavLink>
      <NavLink to="/health/reports/monthly" className={`segmented-option ${!weekly ? 'is-active' : ''}`} aria-current={!weekly ? 'page' : undefined}>Monthly</NavLink>
    </nav>
  )
}

export function MonthlyReportsPage() {
  return (
    <div className="stack">
      <ReportTabs />
      <MonthlyReportsSection />
    </div>
  )
}

/** Health → Weekly reports: the chosen week (default: last complete one) and past weeks. */
export function ReportsSection() {
  const { week } = useParams()
  const report = useWeeklyReport(week ?? null)
  const list = useWeeklyReports()
  const r = report.data

  return (
    <div className="stack">
      <ReportTabs />
      {report.isPending && <section className="card"><Skeleton lines={6} /></section>}
      {report.isError && <ErrorState message={errorText(report.error)} onRetry={() => report.refetch()} />}
      {!report.isPending && !report.isError && !r && (
        <Empty title="No report yet">Your first weekly report arrives on Monday morning, after a full week.</Empty>
      )}
      {r && <WeeklyReportView report={r} />}

      {(list.data?.length ?? 0) > 0 && (
        <section className="card">
          <CardHead title="Past weeks" />
          <ul className="report-list">
            {list.data!.map((w) => (
              <li key={w.id}>
                <Link to={`/health/reports/${w.week_start}`}>
                  <span className="grow">
                    <b>{dayMonth(w.week_start)} – {dayMonth(w.week_end)}</b>
                    <span className="muted small block">{w.runs_done} {w.runs_done === 1 ? 'run' : 'runs'} · {w.km.toFixed(1)} km</span>
                  </span>
                  {r?.week_start === w.week_start && <span className="pill pill-run">Showing</span>}
                  <ChevronRight size={18} className="muted" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

export function WeeklyReportView({ report: r }: { report: WeeklyReport }) {
  const ai = useWeeklyReportAi(r.week_start)
  const zones = (['below', 'Z1', 'Z2', 'Z3', 'Z4', 'Z5'] as const).filter((z) => (r.zones?.[z] ?? 0) > 0)
  const total = r.zones_total_s || zones.reduce((s, z) => s + (r.zones[z] ?? 0), 0)
  const wellness: ThenNowRow[] = (r.wellness ?? [])
    .filter((w) => w.this_week != null && w.previous_week != null)
    .map((w) => ({
      label: w.label,
      then: fmtNum(w.previous_week, w.unit),
      now: fmtNum(w.this_week, w.unit),
      unit: w.unit === 's' ? '' : w.unit,
      delta: w.delta,
      better: w.better == null ? null : (w.delta ?? 0) > 0 === w.better ? 'higher' : 'lower',
    }))
  const habits: ThenNowRow[] = (r.habits ?? []).map((h) => ({
    label: h.habit === 'private' ? '🌙 Private' : h.label,
    then: fmtNum(h.previous_week, ''),
    now: fmtNum(h.this_week, ''),
    delta: h.delta,
    better: h.better == null ? null : h.delta > 0 === h.better ? 'higher' : 'lower',
  }))
  const aiReady = r.ai?.status === 'ready' && !!r.ai.markdown

  return (
    <>
      <section className="card stack">
        <div className="report-head">
          <div className="grow">
            <span className="lbl">Week of {dayMonth(r.week_start)} – {dayMonth(r.week_end)}</span>
            <p className="kit-title">Weekly report</p>
          </div>
          <ShareButton
            label="Share this week"
            card={() => ({ kind: 'week', label: `${dayMonth(r.week_start)} – ${dayMonth(r.week_end)}`, runs: r.runs.done, km: r.runs.km, duration_s: r.runs.time_s })}
          />
        </div>
        <div className="report-grid">
          <div className="report-cell"><b>{r.runs.done}{r.runs.planned ? `/${r.runs.planned}` : ''}</b><span>runs{r.runs.planned ? ' done' : ''}</span></div>
          <div className="report-cell"><b>{r.runs.km.toFixed(1)}</b><span>km · was {r.runs.previous_km.toFixed(1)}</span></div>
          <div className="report-cell"><b>{dur(r.runs.time_s)}</b><span>moving</span></div>
        </div>
        {zones.length > 0 && total > 0 && (
          <div>
            <span className="lbl">Time in zones</span>
            <div className="zone-strip" role="img" aria-label={zones.map((z) => `${z} ${dur(r.zones[z])}`).join(', ')}>
              {zones.map((z) => (
                <span key={z} style={{ flexGrow: r.zones[z], flexBasis: 0, background: ZONE_COLOR[z], color: z === 'below' || z === 'Z1' ? 'var(--fg)' : '#fff' }}>
                  {(r.zones[z] ?? 0) / total > 0.08 ? (z === 'below' ? '<Z1' : z) : ''}
                </span>
              ))}
            </div>
          </div>
        )}
        {r.goal && <div className="goal-box">This week: {r.goal}</div>}
      </section>

      {(r.went_well.length > 0 || r.to_improve.length > 0) && (
        <section className="card stack">
          <CardHead title="How it went" />
          <Bullets items={[...r.went_well.map((t) => ({ tone: 'good', text: t })), ...r.to_improve.map((t) => ({ tone: 'bad', text: t }))]} />
        </section>
      )}

      {r.prs.length > 0 && (
        <section className="card">
          <CardHead title="New records" />
          <Bullets items={r.prs.map((p) => ({ tone: 'good', text: `${p.label}: ${p.display}${p.date ? ` (${dayMonth(p.date)})` : ''}` }))} />
        </section>
      )}

      {wellness.length > 0 && (
        <section className="card">
          <CardHead title="Recovery vs the week before" />
          <ThenNow rows={wellness} />
        </section>
      )}

      {habits.length > 0 && (
        <section className="card">
          <CardHead title="Habits vs the week before" />
          <ThenNow rows={habits} />
        </section>
      )}

      {r.mood && r.mood.days > 0 && (
        <section className="card">
          <CardHead title="Mood & energy" sub={`Average of ${r.mood.days} ${r.mood.days === 1 ? 'day' : 'days'}.`} aside={<InfoButton k="mood" />} />
          <ThenNow rows={[
            ...(r.mood.mood_avg != null ? [{ label: 'Mood', then: r.mood.previous_mood_avg != null ? r.mood.previous_mood_avg.toFixed(1) : '—', now: r.mood.mood_avg.toFixed(1), unit: '/5', delta: r.mood.previous_mood_avg != null ? r.mood.mood_avg - r.mood.previous_mood_avg : undefined, better: 'higher' as const }] : []),
            ...(r.mood.energy_avg != null ? [{ label: 'Energy', then: r.mood.previous_energy_avg != null ? r.mood.previous_energy_avg.toFixed(1) : '—', now: r.mood.energy_avg.toFixed(1), unit: '/5', delta: r.mood.previous_energy_avg != null ? r.mood.energy_avg - r.mood.previous_energy_avg : undefined, better: 'higher' as const }] : []),
          ]} />
        </section>
      )}

      <section className="card stack">
        <CardHead title="Coach’s note" aside={<span className="tag tag-ai"><SparkIcon size={14} /> AI</span>} />
        {aiReady ? (
          <>
            <Markdown text={r.ai!.markdown} />
            {r.ai!.generated_at && <p className="muted small">Written {dateTime(r.ai!.generated_at)}</p>}
          </>
        ) : (
          !ai.isPending && <p className="muted small">A short paragraph on your week from the numbers above. Optional.</p>
        )}
        {ai.isPending && <p className="thinking">Reading your week…</p>}
        {ai.isError && <p className="bad small">{errorText(ai.error, 'The coach could not write this right now.')}</p>}
        <div className="row-end">
          <button type="button" className={`btn ${aiReady ? 'btn-secondary btn-sm' : 'btn-primary'}`} disabled={ai.isPending} onClick={() => ai.mutate(aiReady)}>
            {ai.isPending ? 'Writing…' : aiReady ? 'Rewrite' : 'Write it'}
          </button>
        </div>
      </section>
    </>
  )
}
