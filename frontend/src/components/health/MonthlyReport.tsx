import { Link, useParams } from 'react-router-dom'
import { dateTime, dur } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { useMonthlyReport, useMonthlyReportAi, useMonthlyReports, type MonthlyReport } from '../../lib/r13'
import { Bullets } from '../Bullets'
import { ChevronRight, SparkIcon } from '../Icons'
import { CardHead, ThenNow, type ThenNowRow } from '../Kit'
import { Markdown } from '../Markdown'
import { Empty, ErrorState, Skeleton } from '../States'
import { ShareButton } from '../share/ShareButton'
import { InfoButton } from './InfoButton'

export const monthName = (m: string, long = true) => {
  const [y, mo] = m.split('-').map(Number)
  return new Date(y, (mo || 1) - 1, 1).toLocaleDateString('en-GB', { month: long ? 'long' : 'short', year: 'numeric' })
}

const num = (v: number | null | undefined, unit: string) => {
  if (v == null) return '—'
  if (unit === 's') return dur(v)
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}
const better = (delta: number | null, b: boolean | null): 'higher' | 'lower' | null =>
  b == null || delta == null ? null : (delta > 0) === b ? 'higher' : 'lower'

/** Health → Reports → Monthly: the chosen month (default the last complete one) + list. */
export function MonthlyReportsSection() {
  const { month } = useParams()
  const report = useMonthlyReport(month ?? null)
  const list = useMonthlyReports()
  const r = report.data
  return (
    <div className="stack">
      {report.isPending && <section className="card"><Skeleton lines={6} /></section>}
      {report.isError && <ErrorState message={errorText(report.error, 'This month’s report did not load.')} onRetry={() => report.refetch()} />}
      {!report.isPending && !report.isError && !r && (
        <Empty title="No monthly report yet">Your first one arrives on the 1st of next month, after a full month.</Empty>
      )}
      {r && <MonthlyReportView report={r} />}
      {(list.data?.length ?? 0) > 0 && (
        <section className="card">
          <CardHead title="Past months" />
          <ul className="report-list">
            {list.data!.map((m) => (
              <li key={m.month}>
                <Link to={`/health/reports/monthly/${m.month}`}>
                  <span className="grow">
                    <b>{monthName(m.month)}</b>
                    <span className="muted small block">{m.runs_done} {m.runs_done === 1 ? 'run' : 'runs'} · {m.km.toFixed(1)} km</span>
                  </span>
                  {r?.month === m.month && <span className="pill pill-run">Showing</span>}
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

function MonthlyReportView({ report: r }: { report: MonthlyReport }) {
  const ai = useMonthlyReportAi(r.month)
  const wellness: ThenNowRow[] = r.wellness
    .filter((w) => w.this_month != null && w.previous_month != null)
    .map((w) => ({ label: w.label, then: num(w.previous_month, w.unit), now: num(w.this_month, w.unit), unit: w.unit === 's' ? '' : w.unit, delta: w.delta, better: better(w.delta, w.better) }))
  const habits: ThenNowRow[] = r.habits.map((h) => ({
    label: h.habit === 'private' ? '🌙 Private' : h.label,
    then: num(h.previous_month, ''),
    now: num(h.this_month, ''),
    delta: h.delta,
    better: better(h.delta, h.better),
  }))
  const fit: ThenNowRow[] = []
  if (r.fitness?.vo2max && r.fitness.vo2max.start != null && r.fitness.vo2max.end != null) {
    fit.push({ label: 'VO2max', then: num(r.fitness.vo2max.start, ''), now: num(r.fitness.vo2max.end, ''), delta: r.fitness.vo2max.change, better: 'higher' })
  }
  if (r.fitness?.fitness_age && r.fitness.fitness_age.start != null && r.fitness.fitness_age.end != null) {
    fit.push({ label: 'Fitness age', then: num(r.fitness.fitness_age.start, ''), now: num(r.fitness.fitness_age.end, ''), delta: r.fitness.fitness_age.change, better: 'lower' })
  }
  if (r.weight) fit.push({ label: 'Weight', then: r.weight.start.toFixed(1), now: r.weight.end.toFixed(1), unit: 'kg', delta: r.weight.change, better: null })
  const m = r.mood
  const moodRows: ThenNowRow[] = m && m.days > 0 ? [
    ...(m.mood_avg != null ? [{ label: 'Mood', then: num(m.previous_mood_avg, ''), now: m.mood_avg.toFixed(1), unit: '/5', delta: m.previous_mood_avg != null ? m.mood_avg - m.previous_mood_avg : undefined, better: 'higher' as const }] : []),
    ...(m.energy_avg != null ? [{ label: 'Energy', then: num(m.previous_energy_avg, ''), now: m.energy_avg.toFixed(1), unit: '/5', delta: m.previous_energy_avg != null ? m.energy_avg - m.previous_energy_avg : undefined, better: 'higher' as const }] : []),
  ] : []
  const aiReady = r.ai?.status === 'ready' && !!r.ai.markdown

  return (
    <>
      <section className="card stack">
        <div className="report-head">
          <div className="grow">
            <span className="lbl">{monthName(r.month)}</span>
            <p className="kit-title">Monthly report</p>
          </div>
          <ShareButton
            label="Share this month"
            card={() => ({ kind: 'week', label: monthName(r.month), runs: r.runs.count, km: r.runs.km, duration_s: r.runs.time_s })}
          />
        </div>
        <div className="report-grid">
          <div className="report-cell"><b>{r.runs.count}</b><span>runs · was {r.runs.previous_count}</span></div>
          <div className="report-cell"><b>{r.runs.km.toFixed(1)}</b><span>km · was {r.runs.previous_km.toFixed(1)}</span></div>
          <div className="report-cell"><b>{dur(r.runs.time_s)}</b><span>moving</span></div>
        </div>
        <p className="muted small">
          {r.runs.planned ? `${r.runs.planned_done} of ${r.runs.planned} planned sessions done · ` : ''}longest {r.runs.longest_km.toFixed(1)} km
          {r.smoke_free_days != null ? ` · ${r.smoke_free_days} smoke-free ${r.smoke_free_days === 1 ? 'day' : 'days'}` : ''}
        </p>
        {r.goal && <div className="goal-box">Next month: {r.goal}</div>}
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
          <Bullets items={r.prs.map((p) => ({ tone: 'good', text: `${p.label}: ${p.display}` }))} />
        </section>
      )}

      {fit.length > 0 && (
        <section className="card">
          <CardHead title="Fitness & body" aside={<InfoButton k="vo2max" />} />
          <ThenNow rows={fit} />
        </section>
      )}

      {wellness.length > 0 && (
        <section className="card">
          <CardHead title="Recovery vs the month before" />
          <ThenNow rows={wellness} />
        </section>
      )}

      {habits.length > 0 && (
        <section className="card">
          <CardHead title="Habits vs the month before" />
          <ThenNow rows={habits} />
        </section>
      )}

      {moodRows.length > 0 && (
        <section className="card">
          <CardHead title="Mood & energy" sub={`Average of ${m!.days} ${m!.days === 1 ? 'day' : 'days'} you checked in.`} aside={<InfoButton k="mood" />} />
          <ThenNow rows={moodRows} />
        </section>
      )}

      {r.injury && (r.injury.flags > 0 || r.injury.pain_days > 0) && (
        <section className="card">
          <CardHead title="Injury watch" aside={<InfoButton k="injury_risk" />} />
          <p className="small">
            {r.injury.flags} {r.injury.flags === 1 ? 'flag' : 'flags'} · pain reported on {r.injury.pain_days} {r.injury.pain_days === 1 ? 'day' : 'days'}.
            {r.injury.pain_days > 2 ? ' If something keeps hurting, see a physio.' : ''}
          </p>
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
          !ai.isPending && <p className="muted small">A short paragraph on your month from the numbers above. Optional.</p>
        )}
        {ai.isPending && <p className="thinking">Reading your month…</p>}
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
