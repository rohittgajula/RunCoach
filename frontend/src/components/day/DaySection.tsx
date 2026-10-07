import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Disclosure } from '../Disclose'
import { addDays, parseDate, todayISO } from '../../lib/format'
import { errorText, useDayTrends, useHealthDay } from '../../lib/queries'
import type { DayMarker, DayTrends, HealthDay } from '../../lib/types'
import { ChipButton } from '../ChipButton'
import { guideHref } from '../guides/guideData'
import { ChevronLeft, ChevronRight } from '../Icons'
import { CardHead, Delta, MetricTile, Pill, TopicRing } from '../Kit'
import { InfoButton } from '../health/InfoButton'
import { Empty, ErrorState, Skeleton } from '../States'
import { clock } from '../weather/weatherUtil'
import { DayTimeline, type Lane, type Marker } from './DayTimeline'
import { DayNightRun, StressWeekdays } from './DayTrendsSection'
import { hm, n0, pctOf, stressWord } from './dayUtil'

const MAX_BACK = 365

/** Health → Day: date stepper, timeline, score, steps, sitting, stress, body battery, HR. */
export function DaySection() {
  const [params, setParams] = useSearchParams()
  const today = todayISO()
  const raw = params.get('date')
  const date = raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) && raw <= today ? raw : today
  const day = useHealthDay(date)
  // Weekday pattern and day → night → run come from the 4-week trends.
  const trends = useDayTrends('4w')
  const d = day.data

  const go = (iso: string | null) => {
    if (!iso) return
    const next = new URLSearchParams(params)
    if (iso === today) next.delete('date')
    else next.set('date', iso)
    setParams(next, { replace: true })
  }
  const earliest = addDays(today, -MAX_BACK)
  const prev = d?.date === date ? d.prev_date ?? (date > earliest ? addDays(date, -1) : null) : date > earliest ? addDays(date, -1) : null
  const next = date < today ? (d?.date === date && d.next_date ? d.next_date : addDays(date, 1)) : null

  return (
    <div className={`stack ${day.isPlaceholderData ? 'is-stale' : ''}`}>
      <DayStepper date={date} today={today} onPrev={prev ? () => go(prev) : undefined} onNext={next ? () => go(next) : undefined} onToday={date !== today ? () => go(today) : undefined} asOf={d?.date === date ? d : null} />
      {day.isPending ? (
        <section className="card"><Skeleton height={300} /></section>
      ) : day.isError && !d ? (
        <ErrorState message={errorText(day.error, 'This day did not load.')} onRetry={() => day.refetch()} />
      ) : !d || !d.available ? (
        <Empty title={date === today ? 'Nothing from your watch yet today' : 'No daytime data for this day'}>
          {date === today
            ? 'Heart rate, stress, Body Battery and steps show up here after your watch syncs with Garmin Connect. Some watches don’t record all of them.'
            : 'Your watch didn’t send all-day data for this day (it may not have been worn, or this watch doesn’t record it).'}
        </Empty>
      ) : (
        <>
          {/* R14 §1: summary first, then the timeline; the per-metric cards are one tap down. */}
          <ScoreCard d={d} />
          <TimelineCard d={d} />
          <Disclosure id="day-details" title="Steps, sitting, stress, Body Battery, awake HR" sub="Each one in detail, with what’s normal for you">
            <StepsCard d={d} />
            <SittingCard d={d} />
            <StressCard d={d} trends={trends.data ?? null} />
            <BodyBatteryCard d={d} />
            <AwakeHrCard d={d} />
            {trends.data?.day_night_run && <DayNightRun dnr={trends.data.day_night_run} />}
          </Disclosure>
        </>
      )}
      {(!d || !d.available) && trends.data?.day_night_run && <DayNightRun dnr={trends.data.day_night_run} />}
      <Link to="/health/day/trends" className="card link-row">
        <span className="grow">
          <span className="link-row-title">Trends</span>
          <span className="link-row-text">Steps, sitting, stress and awake heart rate over weeks</span>
        </span>
        <ChevronRight size={18} className="muted" />
      </Link>
    </div>
  )
}

function DayStepper({ date, today, onPrev, onNext, onToday, asOf }: {
  date: string; today: string; onPrev?: () => void; onNext?: () => void; onToday?: () => void; asOf: HealthDay | null
}) {
  const label = date === today ? 'Today' : date === addDays(today, -1) ? 'Yesterday'
    : parseDate(date).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
  const sub = asOf?.available && asOf.data_as_of
    ? (asOf.is_today ? `Data up to ${clock(asOf.data_as_of)} · last sync` : asOf.complete ? 'Full day' : `Data up to ${clock(asOf.data_as_of)}`)
    : parseDate(date).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
  return (
    <div className="card day-stepper" role="group" aria-label="Choose a day">
      <ChipButton label="Previous day" onClick={onPrev} disabled={!onPrev} className="chip-plain"><ChevronLeft size={20} /></ChipButton>
      <div className="grow">
        <span className="day-stepper-label" aria-live="polite">{label}</span>
        <span className="day-stepper-sub">{sub}</span>
      </div>
      {onToday ? (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onToday}>Today</button>
      ) : null}
      <ChipButton label="Next day" onClick={onNext} disabled={!onNext} className="chip-plain"><ChevronRight size={20} /></ChipButton>
    </div>
  )
}

// --- timeline ------------------------------------------------------------------------

/** Shade 51+ (medium/high — Garmin's "stressful"). */
const STRESS_BANDS = [{ from: 51, to: 100, color: 'var(--recovery)' }]

function toMarkers(list: DayMarker[]): Marker[] {
  return list.map((m) => ({
    kind: m.type,
    start: m.start_min,
    end: m.end_min,
    // Private habit: the moon only, never a word (and only sent while it is enabled).
    label: m.type === 'habit' && m.kind === 'private' ? '🌙' : m.label,
  }))
}

function TimelineCard({ d }: { d: HealthDay }) {
  const t = d.timeline
  const lanes: Lane[] = useMemo(() => {
    const out: Lane[] = []
    if (t.hr.length) out.push({ key: 'hr', label: 'Heart rate', unit: 'bpm', color: 'var(--recovery-ink)', kind: 'line', points: t.hr, format: (v) => `${Math.round(v)} bpm` })
    if (t.stress.length) out.push({ key: 'stress', label: 'Stress', color: 'var(--recovery)', kind: 'line', points: t.stress, domain: [0, 100], bands: STRESS_BANDS, format: (v) => `${Math.round(v)} · ${stressWord(v)}` })
    if (t.body_battery.length) out.push({ key: 'bb', label: 'Body Battery', color: 'var(--sleep)', kind: 'line', points: t.body_battery, domain: [0, 100], step: 15, maxGap: 120 })
    if (t.steps.length) out.push({ key: 'steps', label: 'Steps', unit: 'per 15 min', color: 'var(--run)', kind: 'bars', points: t.steps, step: 15, format: (v) => `${n0(v)} steps` })
    return out
  }, [t])
  const markers = useMemo(() => toMarkers(t.markers), [t.markers])
  const now = d.is_today && d.data_as_of ? minutesOf(d.data_as_of) : null
  if (!lanes.length) return null
  const kinds = new Set(markers.map((m) => m.kind))
  return (
    <section className="card">
      <CardHead title="Your day" sub="Drag across to read every line at that time" />
      <DayTimeline lanes={lanes} markers={markers} nowMinute={now} label={`Heart rate, stress, Body Battery and steps through ${d.is_today ? 'today' : 'the day'}`} />
      <div className="tl-legend">
        {kinds.has('sleep') && <span><i style={{ background: 'var(--sleep)' }} />Sleep</span>}
        {kinds.has('nap') && <span><i style={{ background: 'var(--sleep)', opacity: 0.6 }} />Nap</span>}
        {kinds.has('run') && <span><i style={{ background: 'var(--run)' }} />Run</span>}
        {kinds.has('habit') && <span><i style={{ background: 'var(--habits)', borderRadius: '50%', width: 8 }} />Habit log</span>}
        {lanes.some((l) => l.key === 'stress') && <span><i style={{ background: 'var(--recovery)', opacity: 0.25 }} />Stress 51+ (stressful)</span>}
      </div>
    </section>
  )
}

const minutesOf = (hhmm: string) => {
  const m = /(\d{1,2}):(\d{2})/.exec(hhmm)
  return m ? Number(m[1]) * 60 + Number(m[2]) : null
}

// --- score card ----------------------------------------------------------------------

function ScoreCard({ d }: { d: HealthDay }) {
  const s = d.score_card
  if (!s || (!s.sentence && !s.bullets.length)) return null
  const pill = s.status === 'good' ? <Pill topic="ok">Good day</Pill> : s.status === 'low' ? <Pill topic="bad">Hard day</Pill> : s.status === 'ok' ? <Pill topic="ink">OK day</Pill> : <Pill>Not enough data</Pill>
  return (
    <section className="card">
      <CardHead title={d.is_today ? 'So far today' : 'How the day went'} aside={pill} />
      {s.sentence && <p className="score-sentence">{s.sentence}</p>}
      {s.bullets.length > 0 && (
        <ul className="bullets" style={{ marginTop: 10 }}>
          {s.bullets.map((b) => <li key={b} className="bullet"><span className="bullet-dot" aria-hidden="true" /><span>{b}</span></li>)}
        </ul>
      )}
      {s.tips.length > 0 && (
        <>
          <p className="lbl" style={{ marginTop: 12 }}>For tomorrow</p>
          <ul className="bullets" style={{ marginTop: 6 }}>
            {s.tips.map((b) => <li key={b} className="bullet is-run"><span className="bullet-dot" aria-hidden="true" /><span>{b}</span></li>)}
          </ul>
        </>
      )}
    </section>
  )
}

// --- steps ---------------------------------------------------------------------------

function StepsCard({ d }: { d: HealthDay }) {
  const s = d.steps
  if (s.total == null && !s.hourly.some((h) => h.steps)) return null
  const goal = s.goal
  const maxHour = Math.max(1, ...s.hourly.map((h) => h.steps))
  const goalNote = goal == null ? 'No step goal yet — needs a week of data'
    : s.goal_source === 'garmin' ? `Goal ${n0(goal)} (your Garmin goal)` : `Goal ${n0(goal)} (from your last 4 weeks)`
  return (
    <section className="card">
      <CardHead title={<span className="title-info">Steps<InfoButton k="steps" /></span>} aside={s.met ? <Pill topic="ok">Goal hit</Pill> : undefined} />
      <div className="steps-hero">
        <TopicRing value={s.total ?? 0} max={goal || Math.max(s.total ?? 1, 1)} topic="run" size={96} label="Steps" display={s.total != null ? compact(s.total) : '--'} sub={goal ? `${pctOf(s.pct)}` : undefined} />
        <div className="grow">
          <span className="big-num" style={{ fontSize: 30 }}>{s.total != null ? n0(s.total) : '—'}</span>
          <span className="muted small">{goalNote}</span>
          <span className="row-wrap">
            {s.trend.change_pct != null && <Delta value={s.trend.change_pct} better="higher" unit="%" flatWithin={2} suffix="7-day avg" />}
            {s.streak_days > 1 && <Pill topic="run">{s.streak_days}-day goal streak</Pill>}
          </span>
        </div>
      </div>
      {s.hourly.length === 24 && (
        <>
          <div className="hour-bars" style={{ marginTop: 14 }} role="img" aria-label={s.most_active_hour ? `Most active ${s.most_active_hour.label}` : 'Steps per hour'}>
            {s.hourly.map((h) => (
              <span key={h.hour} style={{ height: `${Math.max(4, (h.steps / maxHour) * 100)}%`, background: h.hour === s.most_active_hour?.hour ? 'var(--run)' : 'var(--run-soft)' }} title={`${h.hour}:00 · ${n0(h.steps)}`} />
            ))}
          </div>
          <div className="hour-labels" style={{ marginTop: 4 }}><span>{clock('00:00')}</span><span>{clock('06:00')}</span><span>{clock('12:00')}</span><span>{clock('18:00')}</span><span>{clock('23:00')}</span></div>
        </>
      )}
      <div className="mt-grid" style={{ marginTop: 12 }}>
        {s.most_active_hour && <MetricTile className="mt-inset" label="Most active" value={hourText(s.most_active_hour.label)} sub={`${n0(s.most_active_hour.steps)} steps`} />}
        {s.trend.last7_avg != null && <MetricTile className="mt-inset" label="7-day average" value={n0(s.trend.last7_avg)} sub={s.trend.prev7_avg != null ? `week before ${n0(s.trend.prev7_avg)}` : undefined} />}
        {s.run_days_avg != null && <MetricTile className="mt-inset" label="Run days" value={n0(s.run_days_avg)} sub={`avg · ${s.run_days_n} days`} />}
        {s.rest_days_avg != null && <MetricTile className="mt-inset" label="Rest days" value={n0(s.rest_days_avg)} sub={`avg · ${s.rest_days_n} days`} />}
      </div>
    </section>
  )
}

const compact = (v: number) => (v >= 10000 ? `${(v / 1000).toFixed(1)}k` : n0(v))
/** "14:00–15:00" → "2–3 pm" style via the locale clock. */
const hourText = (label: string) => {
  const m = /(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})/.exec(label)
  return m ? `${clock(m[1])}` : label
}

// --- active vs sedentary ---------------------------------------------------------------

function SittingCard({ d }: { d: HealthDay }) {
  const a = d.activity
  const parts = [
    { key: 'sed', label: 'Sitting / still', v: a.sedentary_min, cls: 'st-sed' },
    { key: 'act', label: 'Active', v: a.active_min, cls: 'st-act' },
    { key: 'int', label: 'Intense', v: a.intense_min, cls: 'st-int' },
  ]
  const total = parts.reduce((s, p) => s + (p.v ?? 0), 0)
  if (!total) return null
  const ls = a.longest_sedentary
  return (
    <section className="card">
      <CardHead title={<span className="title-info">Moving vs sitting<InfoButton k="sedentary_min" /></span>} sub={`While awake${a.source === 'steps' ? ' · estimated from your steps' : ''}`} />
      <div className="stack-bar" role="img" aria-label={parts.map((p) => `${p.label} ${hm((p.v ?? 0) * 60)}`).join(', ')}>
        {parts.filter((p) => p.v).map((p) => <span key={p.key} className={p.cls} style={{ flexGrow: p.v!, flexBasis: 0 }} />)}
      </div>
      <div className="stack-legend">
        {parts.map((p) => (
          <div key={p.key}><i className={p.cls} /><span>{p.label}</span><b>{p.v != null ? hm(p.v * 60) : '—'}</b></div>
        ))}
      </div>
      {ls && ls.minutes >= 30 && (
        <p className="callout">
          Longest sitting stretch: <b>{hm(ls.minutes * 60)}</b>, {clock(ls.start)}–{clock(ls.end)}.
          {ls.minutes >= 90 ? ' A 3-minute walk every hour breaks it up.' : ''}
        </p>
      )}
    </section>
  )
}

// --- stress ----------------------------------------------------------------------------

function StressCard({ d, trends }: { d: HealthDay; trends: DayTrends | null }) {
  const s = d.stress
  const parts = [
    { key: 'rest', label: 'Rest', v: s.rest_min, cls: 'str-rest' },
    { key: 'low', label: 'Low', v: s.low_min, cls: 'str-low' },
    { key: 'med', label: 'Medium', v: s.medium_min, cls: 'str-med' },
    { key: 'high', label: 'High', v: s.high_min, cls: 'str-high' },
  ]
  const total = parts.reduce((a, p) => a + p.v, 0)
  if (!total && s.avg == null) return null
  const longest = [...s.stretches].sort((a, b) => b.minutes - a.minutes)[0]
  return (
    <section className="card">
      <CardHead
        title={<span className="title-info">Stress<InfoButton k="stress" /></span>}
        sub={s.avg != null ? `Average ${s.avg} · ${stressWord(s.avg)}${s.max != null ? ` · peak ${s.max}` : ''}` : undefined}
      />
      {total > 0 && (
        <>
          <div className="stack-bar" role="img" aria-label={parts.map((p) => `${p.label} ${hm(p.v * 60)}`).join(', ')}>
            {parts.filter((p) => p.v).map((p) => <span key={p.key} className={p.cls} style={{ flexGrow: p.v, flexBasis: 0 }} />)}
          </div>
          <div className="stack-legend">
            {parts.map((p) => <div key={p.key}><i className={p.cls} /><span>{p.label}</span><b>{hm(p.v * 60)}</b></div>)}
          </div>
        </>
      )}
      {s.peak && <p className="callout">Most stressful hour: <b>{clock(s.peak.start)}–{clock(s.peak.end)}</b> (avg {s.peak.avg}).</p>}
      {longest && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {s.stretches.length === 1 ? 'One stretch' : `${s.stretches.length} stretches`} of 30+ min at medium/high stress — longest {hm(longest.minutes * 60)} from {clock(longest.start)}.{' '}
          <Link to={guideHref('breathing')}>Try a breathing break</Link>
        </p>
      )}
      {trends && <StressWeekdays t={trends} />}
    </section>
  )
}

// --- body battery --------------------------------------------------------------------

const CAUSE: Record<string, string> = { sleep: 'Sleep', nap: 'Nap', run: 'Run', stress: 'Stressful stretch', rest: 'Rest', activity: 'Activity' }

function BodyBatteryCard({ d }: { d: HealthDay }) {
  const b = d.body_battery
  if (b.charged == null && b.drained == null && b.at_wake == null && !b.events.length) return null
  const events = [...b.events].sort((x, y) => (minutesOf(x.start) ?? 0) - (minutesOf(y.start) ?? 0))
  return (
    <section className="card">
      <CardHead title={<span className="title-info">Body Battery<InfoButton k="body_battery" /></span>} sub={[b.charged != null && `+${b.charged} charged`, b.drained != null && `−${b.drained} drained`].filter(Boolean).join(' · ') || undefined} />
      <div className="bb-ends">
        <MetricTile className="mt-inset" label="At wake" value={b.at_wake ?? '—'} sub={d.awake ? clock(d.awake.start) : undefined} />
        {d.is_today ? (
          <MetricTile className="mt-inset" label="Now" value={b.now ?? '—'} sub={d.now.body_battery_at ? `at ${clock(d.now.body_battery_at)}` : undefined} />
        ) : (
          <MetricTile className="mt-inset" label="At bedtime" value={b.at_bedtime ?? '—'} sub={d.awake ? clock(d.awake.end) : undefined} />
        )}
      </div>
      {events.length > 0 && (
        <ul className="bb-list">
          {events.map((e, i) => (
            <li key={i} className="bb-item">
              <span className="grow">
                <strong>{CAUSE[e.cause] ?? e.cause}</strong>
                <span className="bb-when block">{clock(e.start)}–{clock(e.end)} · {e.from_value} → {e.to_value}</span>
              </span>
              <span className={`bb-delta ${e.type === 'charge' ? 'is-up' : 'is-down'}`} aria-label={`${e.type === 'charge' ? 'charged' : 'drained'} ${e.amount}`}>
                {e.type === 'charge' ? '▲ +' : '▼ −'}{e.amount}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// --- awake heart rate -------------------------------------------------------------------

function AwakeHrCard({ d }: { d: HealthDay }) {
  const h = d.heart_rate
  if (h.awake_avg == null && h.resting == null) return null
  return (
    <section className="card">
      <CardHead
        title={<span className="title-info">Heart rate while awake<InfoButton k="awake_hr" /></span>}
        sub="Not counting sleep and workouts"
        aside={<Delta value={h.trend.change} better="lower" unit="bpm" flatWithin={0.5} suffix="vs last wk" />}
      />
      <div className="report-grid">
        <div className="report-cell"><b>{h.awake_min ?? '—'}</b><span>lowest</span></div>
        <div className="report-cell"><b>{h.awake_avg ?? '—'}</b><span>average</span></div>
        <div className="report-cell"><b>{h.awake_max ?? '—'}</b><span>highest</span></div>
      </div>
      <p className="muted small" style={{ marginTop: 8 }}>
        {h.resting != null && `Resting ${h.resting} bpm. `}
        {h.trend.this_week_avg != null && `This week’s awake average ${h.trend.this_week_avg} bpm${h.trend.prev_week_avg != null ? ` (week before ${h.trend.prev_week_avg})` : ''}.`}
      </p>
    </section>
  )
}
