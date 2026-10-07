import { useState } from 'react'
import { Link } from 'react-router-dom'
import { errorText, useDayTrends } from '../../lib/queries'
import type { DayTrendAvg, DayTrends } from '../../lib/types'
import { ChartFrame } from '../ChartFrame'
import { ChevronLeft } from '../Icons'
import { CardHead, Delta, MetricTile, Pill } from '../Kit'
import { MetricChart } from '../MetricChart'
import { RangeSwitch } from '../RangeSwitch'
import { Empty, ErrorState, Skeleton } from '../States'
import { clock } from '../weather/weatherUtil'
import { n0 } from './dayUtil'

const RANGES = [
  { value: '7d', label: '7d' },
  { value: '4w', label: '4w' },
  { value: '3m', label: '3m' },
  { value: '6m', label: '6m' },
]

type Tile = { key: keyof DayTrendAvg; label: string; unit?: string; better: 'higher' | 'lower'; flat: number }
const TILES: Tile[] = [
  { key: 'steps', label: 'Steps / day', better: 'higher', flat: 150 },
  { key: 'active_min', label: 'Active', unit: 'min', better: 'higher', flat: 2 },
  { key: 'sedentary_min', label: 'Sitting', unit: 'min', better: 'lower', flat: 5 },
  { key: 'stress_avg', label: 'Stress avg', better: 'lower', flat: 1 },
  { key: 'stress_high_min', label: 'High stress', unit: 'min', better: 'lower', flat: 2 },
  { key: 'awake_hr_avg', label: 'Awake HR', unit: 'bpm', better: 'lower', flat: 0.5 },
  { key: 'bb_at_bedtime', label: 'Battery at bedtime', better: 'higher', flat: 1 },
]

/** Health → Day → Trends: the day metrics over weeks, weekday pattern, day → night → run. */
export function DayTrendsSection() {
  const [range, setRange] = useState('4w')
  const q = useDayTrends(range)
  const t = q.data

  const head = (
    <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
      <Link to="/health/day" className="btn btn-secondary btn-sm"><ChevronLeft size={18} /> Day</Link>
      <RangeSwitch compact value={range} onChange={setRange} options={RANGES} label="Range" />
    </div>
  )
  if (q.isPending) return <div className="stack">{head}<section className="card"><Skeleton height={220} /></section></div>
  if (q.isError && !t) return <div className="stack">{head}<ErrorState message={errorText(q.error, 'Trends did not load.')} onRetry={() => q.refetch()} /></div>
  const any = t?.days.some((d) => d.steps != null || d.stress_avg != null || d.awake_hr_avg != null)
  if (!t || !any) {
    return (
      <div className="stack">
        {head}
        <Empty title="No daytime data yet">Steps, stress and heart rate through the day show up here once your watch has synced a few days.</Empty>
      </div>
    )
  }
  const series = (k: keyof DayTrends['days'][number]) => t.days.map((d) => ({ date: d.date, value: (d[k] as number | null) ?? null }))
  const enough = (k: keyof DayTrends['days'][number]) => t.days.filter((d) => d[k] != null).length >= 3
  const goals = t.days.map((d) => d.step_goal).filter((g): g is number => g != null)
  const goal = goals.length ? goals[goals.length - 1] : null

  return (
    <div className={`stack ${q.isPlaceholderData ? 'is-stale' : ''}`}>
      {head}
      <div className="mt-grid">
        {TILES.filter((tile) => t.averages[tile.key] != null).map((tile) => {
          const now = t.averages[tile.key] as number
          const before = t.previous?.[tile.key]
          return (
            <MetricTile
              key={tile.key}
              label={tile.label}
              value={n0(now)}
              unit={tile.unit}
              chip={<Delta value={before != null ? now - before : null} better={tile.better} flatWithin={tile.flat} format={(v) => n0(v)} />}
              sub={before != null ? `before ${n0(before)}` : undefined}
            />
          )
        })}
      </div>

      {enough('steps') && (
        <section className="card">
          <ChartFrame title="Steps" chip={t.goal_streak > 1 ? <Pill topic="run">{t.goal_streak}-day streak</Pill> : undefined} caption={goal ? `Shaded = within 10% of your ${n0(goal)} goal.` : 'Dashed line = your average.'}>
            <MetricChart data={series('steps')} color="var(--run)" height={180} format={(v) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : String(Math.round(v)))} band={goal ? { low: goal * 0.9, high: goal * 1.1, label: 'goal' } : null} />
          </ChartFrame>
        </section>
      )}
      {enough('active_min') && (
        <section className="card">
          <ChartFrame title="Active minutes" caption="Walking, runs and anything that gets you moving.">
            <MetricChart data={series('active_min')} color="var(--run)" height={160} />
          </ChartFrame>
        </section>
      )}
      {enough('stress_avg') && (
        <section className="card">
          <ChartFrame title="Stress average" caption="0–25 rest · 26–50 low · 51–75 medium · 76–100 high.">
            <MetricChart data={series('stress_avg')} color="var(--recovery)" height={160} />
          </ChartFrame>
        </section>
      )}
      {enough('awake_hr_avg') && (
        <section className="card">
          <ChartFrame title="Heart rate while awake" caption={t.awake_hr_trend.sentence || 'Not counting sleep and workouts.'}>
            <MetricChart data={series('awake_hr_avg')} color="var(--recovery-ink)" height={160} />
          </ChartFrame>
        </section>
      )}
      {enough('bb_at_bedtime') && (
        <section className="card">
          <ChartFrame title="Body Battery at bedtime" caption="Going to bed with more left usually means a calmer day.">
            <MetricChart data={series('bb_at_bedtime')} color="var(--sleep)" height={160} domain={[0, 100]} />
          </ChartFrame>
        </section>
      )}

      <WeekdayCard t={t} />
      {t.day_night_run && <DayNightRun dnr={t.day_night_run} />}
    </div>
  )
}

function WeekdayCard({ t }: { t: DayTrends }) {
  const w = t.weekday_pattern
  const rows = w.by_weekday
  if (!rows.some((r) => r.steps_avg != null || r.stress_avg != null)) return null
  const maxSteps = Math.max(1, ...rows.map((r) => r.steps_avg ?? 0))
  return (
    <section className="card">
      <CardHead title="Your week" sub="Average by weekday" />
      <p className="lbl">Steps</p>
      <div className="week-pattern" role="img" aria-label={rows.map((r) => `${r.label} ${n0(r.steps_avg)} steps`).join(', ')}>
        {rows.map((r) => (
          <div key={r.weekday}>
            <span className="bar" style={{ height: `${Math.max(4, ((r.steps_avg ?? 0) / maxSteps) * 100)}%`, background: 'var(--run)' }} />
            <small>{r.label}</small>
          </div>
        ))}
      </div>
      <StressWeekdays t={t} />
    </section>
  )
}

/** Stress by weekday + the "peaks 11–12 on weekdays" sentence. Used on Day and Trends. */
export function StressWeekdays({ t }: { t: DayTrends }) {
  const w = t.weekday_pattern
  const rows = w.by_weekday
  if (!rows.some((r) => r.stress_avg != null)) return null
  const peak = w.stress_peak_weekdays
  const weekend = w.stress_peak_weekends
  // Relative to the most stressful weekday, so the pattern shows.
  const max = Math.max(1, ...rows.map((r) => r.stress_avg ?? 0))
  return (
    <div style={{ marginTop: 14 }}>
      <p className="lbl">Stress by weekday · last {t.range}</p>
      <div className="week-pattern" role="img" aria-label={rows.map((r) => `${r.label} ${r.stress_avg ?? 'no data'}`).join(', ')}>
        {rows.map((r) => (
          <div key={r.weekday}>
            <span className="bar" style={{ height: `${Math.max(4, ((r.stress_avg ?? 0) / max) * 100)}%` }} title={`${r.label}: ${r.stress_avg ?? '—'}`} />
            <small>{r.label}</small>
          </div>
        ))}
      </div>
      {(w.sentence || peak) && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {w.sentence ?? `Stress tends to peak ${clock(peak!.start)}–${clock(peak!.end)} on weekdays.`}
          {weekend && ` Weekends: ${clock(weekend.start)}–${clock(weekend.end)}.`}
        </p>
      )}
    </div>
  )
}

const fmt = (v: number, unit: string) => (unit === 'h' ? v.toFixed(1) : Math.abs(v) >= 10 ? String(Math.round(v)) : v.toFixed(1))
/** Lower is better for these; the rest are higher-better. */
const LOWER_BETTER = new Set(['easy_hr'])

/** Busy / stressful days vs that night's sleep and the next run. Association only. */
export function DayNightRun({ dnr }: { dnr: NonNullable<DayTrends['day_night_run']> }) {
  const groups = dnr.groups.filter((g) => g.rows.length)
  if (!groups.length) return null
  return (
    <section className="card">
      <CardHead title="Day → night → run" sub="How busy or stressful days line up with that night’s sleep and your next run" />
      {groups.map((g, gi) => (
        <div key={g.key} style={{ marginTop: gi ? 18 : 8 }}>
          <p className="kit-title" style={{ fontSize: 14 }}>{g.label}</p>
          <div className="dnr-head" style={{ marginTop: 6 }}>
            <span />
            <span>{g.high_label}</span>
            <span>{g.low_label}</span>
          </div>
          {g.rows.map((r) => {
            const better = LOWER_BETTER.has(r.metric) ? 'lower' : 'higher'
            const d = r.enough_data && r.high != null && r.low != null ? r.high - r.low : null
            const tone = d == null || Math.abs(d) < 1e-9 ? null : (d > 0) === (better === 'higher') ? 'good' : 'bad'
            return (
              <div key={r.metric} className="dnr-row" title={r.sentence}>
                <span>{r.label}{r.unit ? <span className="muted small"> {r.unit}</span> : null}</span>
                <b className={tone === 'good' ? 'good-text' : tone === 'bad' ? 'bad' : ''}>
                  {r.high != null && r.enough_data ? fmt(r.high, r.unit) : '—'}
                  {tone && <span aria-hidden="true" style={{ fontSize: 10, marginLeft: 3 }}>{d! > 0 ? '▲' : '▼'}</span>}
                </b>
                <b>{r.low != null && r.enough_data ? fmt(r.low, r.unit) : '—'}</b>
              </div>
            )
          })}
          {g.rows.filter((r) => r.enough_data && r.sentence).slice(0, 2).map((r) => <p key={r.metric} className="muted small" style={{ marginTop: 4 }}>{r.sentence}</p>)}
          {!g.rows.some((r) => r.enough_data) && <p className="muted small">Not enough days on each side yet ({g.n_high} vs {g.n_low}).</p>}
        </div>
      ))}
      <p className="chart-caption" style={{ marginTop: 10 }}>{dnr.caveat}</p>
    </section>
  )
}
