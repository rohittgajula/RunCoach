import { Link } from 'react-router-dom'
import { dur, parseDate } from '../../lib/format'
import { errorText, useHealthSleep, useWakePlan } from '../../lib/queries'
import type { HealthSleep, SleepNight } from '../../lib/types'
import { ChartFrame } from '../ChartFrame'
import { guideHref } from '../guides/guideData'
import { WakePlannerCard, WatchAlarmsCard } from '../alarm/AlarmCards'
import { CardHead, Delta, MetricTile, ToneChip } from '../Kit'
import { MetricChart } from '../MetricChart'
import { Empty, ErrorState, Skeleton } from '../States'
import { clock } from '../weather/weatherUtil'
import { FREQ_WORD, bucket, periodCaption, useHealthPeriod, withApiPeriod, type Period } from './healthRange'

/** "YYYY-MM-DDTHH:MM" / "HH:MM" → minutes after 18:00 the evening before (so 01:00 = 420). */
function eveningMinutes(t: string | null): number | null {
  if (!t) return null
  const m = /(?:T|^)(\d{1,2}):(\d{2})/.exec(t)
  if (!m) return null
  const mins = Number(m[1]) * 60 + Number(m[2])
  return (mins - 18 * 60 + 24 * 60) % (24 * 60)
}
const fromEvening = (m: number) => {
  const total = (m + 18 * 60) % (24 * 60)
  const d = new Date()
  d.setHours(Math.floor(total / 60), total % 60, 0, 0)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: total % 60 ? '2-digit' : undefined })
}
const hm = (s: number | null | undefined) => (s == null ? '—' : dur(s))
const dow = (iso: string) => parseDate(iso).toLocaleDateString(undefined, { weekday: 'short' })

/** Health → Sleep: average + debt, stages timeline, regularity, SpO2, breathing, runs, tonight. */
export function SleepSection() {
  const { period: chosen } = useHealthPeriod()
  const sleep = useHealthSleep(chosen.params)
  const s = sleep.data
  const period = withApiPeriod(chosen, s?.period)

  if (sleep.isPending) return <div className="stack"><section className="card"><Skeleton height={220} /></section></div>
  if (sleep.isError && !s) return <ErrorState message={errorText(sleep.error, 'Sleep did not load.')} onRetry={() => sleep.refetch()} />
  if (!s || !s.nights.length) {
    return (
      <div className="stack">
        <Empty title="No sleep data yet">Wear your watch to bed and sync — nights show up here with stages, debt and regularity.</Empty>
        <WakePlannerCard />
        <WatchAlarmsCard showFlags={false} />
      </div>
    )
  }

  return (
    <div className={`stack ${sleep.isPlaceholderData ? 'is-stale' : ''}`}>
      <SleepHero s={s} />
      <SleepTiles s={s} />
      <SleepTrend nights={s.series?.length ? s.series : s.nights} need={s.debt?.need_s ?? s.averages?.need_s ?? null} period={period} />
      <SleepVsRuns s={s} />
      <WakePlannerCard />
      <WatchAlarmsCard showFlags={false} />
      <Tonight s={s} />
    </div>
  )
}

function SleepHero({ s }: { s: HealthSleep }) {
  const avg = s.averages
  const debt = s.debt
  const nights = s.nights.filter((n) => n.bedtime && n.wake_time).slice(-7)
  const starts = nights.map((n) => eveningMinutes(n.bedtime)!).filter((v) => v != null)
  const ends = nights.map((n) => {
    const b = eveningMinutes(n.bedtime)!
    const w = eveningMinutes(n.wake_time)!
    return w < b ? w + 24 * 60 : w
  })
  const lo = Math.max(0, Math.floor((Math.min(...starts) - 10) / 60) * 60)
  const hi = Math.ceil((Math.max(...ends) + 10) / 60) * 60
  const span = hi - lo || 1
  const pct = (m: number) => `${((m - lo) / span) * 100}%`
  return (
    <section className="card">
      <div className="kit-head" style={{ alignItems: 'flex-start', marginBottom: 4 }}>
        <div className="grow">
          <span className="lbl">Average sleep</span>
          <div className="big-num" style={{ fontSize: 36 }}>{hm(avg?.sleep_s)}</div>
        </div>
        {debt?.debt_s != null && (
          debt.debt_s > 15 * 60
            ? <ToneChip tone="bad">Debt {hm(debt.debt_s)}</ToneChip>
            : <ToneChip tone="good">No sleep debt</ToneChip>
        )}
      </div>
      {(debt?.need_s || avg?.need_s) && (
        <p className="muted small">
          You need about {hm(debt?.need_s ?? avg?.need_s)}.
          {debt && debt.short_nights > 0 && debt.short_by_s ? ` Short by ~${hm(debt.short_by_s)} on ${debt.short_nights} of ${debt.nights} nights.` : ''}
        </p>
      )}
      {nights.length > 0 && Number.isFinite(span) && (
        <>
          <div className="sleep-nights" role="img" aria-label={`Sleep stages for the last ${nights.length} nights`}>
            {nights.map((n, i) => <NightRow key={n.date} n={n} left={pct(starts[i])} width={`${((ends[i] - starts[i]) / span) * 100}%`} />)}
          </div>
          <div className="sleep-axis">
            <span>{fromEvening(lo)}</span>
            <span>{fromEvening(Math.round((lo + span / 2) / 60) * 60)}</span>
            <span>{fromEvening(hi)}</span>
          </div>
          <div className="sleep-legend">
            <span><i className="st-deep" />Deep</span><span><i className="st-light" />Light</span><span><i className="st-rem" />REM</span><span><i className="st-awake" />Awake</span>
          </div>
        </>
      )}
    </section>
  )
}

function NightRow({ n, left, width }: { n: SleepNight; left: string; width: string }) {
  const parts: Array<[string, number | null]> = [['st-deep', n.deep_s], ['st-light', n.light_s], ['st-rem', n.rem_s], ['st-awake', n.awake_s]]
  const known = parts.some(([, v]) => v)
  return (
    <div className="sleep-night" title={`${dow(n.date)}: ${hm(n.sleep_s)}`}>
      <span>{dow(n.date)}</span>
      <div className="sleep-track">
        <div className="sleep-bar" style={{ left, width }}>
          {known
            ? parts.filter(([, v]) => v).map(([cls, v]) => <span key={cls} className={cls} style={{ flexGrow: v!, flexBasis: 0 }} />)
            : <span className="st-light" style={{ flexGrow: 1 }} />}
        </div>
      </div>
    </div>
  )
}

function SleepTiles({ s }: { s: HealthSleep }) {
  const a = s.averages
  const p = s.previous
  const r = s.regularity
  const tiles = []
  if (r?.bedtime_sd_min != null) {
    const d = r.previous_bedtime_sd_min != null ? r.bedtime_sd_min - r.previous_bedtime_sd_min : null
    tiles.push(
      <MetricTile key="reg" label="Bedtime regularity" value={`±${Math.round(r.bedtime_sd_min)}`} unit="min"
        sub={d != null && Math.abs(d) >= 5 ? <span className={d < 0 ? 'good-text' : 'bad'}>{d < 0 ? '▼ more regular' : '▲ less regular'}</span> : a?.bedtime ? `usually ${clock(a.bedtime)}` : undefined} />,
    )
  }
  if (a?.deep_s != null) {
    tiles.push(<MetricTile key="deep" label="Deep sleep" value={hm(a.deep_s)} chip={<Delta value={p?.deep_s != null ? (a.deep_s - p.deep_s) / 60 : null} better="higher" unit="min" flatWithin={2} />} />)
  }
  if (a?.score != null) {
    tiles.push(<MetricTile key="score" label="Sleep score" value={Math.round(a.score)} chip={<Delta value={p?.score != null ? a.score - p.score : null} better="higher" flatWithin={1} />} />)
  }
  if (a?.spo2_avg != null) {
    tiles.push(<MetricTile key="spo2" label="SpO2" value={`${Math.round(a.spo2_avg)}%`} chip={<Delta value={p?.spo2_avg != null ? a.spo2_avg - p.spo2_avg : null} better="higher" format={(v) => v.toFixed(1)} flatWithin={0.5} />} />)
  }
  if (a?.breathing_rate != null) {
    tiles.push(<MetricTile key="br" label="Breathing rate" value={a.breathing_rate.toFixed(1)} unit="/min" chip={<Delta value={p?.breathing_rate != null ? a.breathing_rate - p.breathing_rate : null} better="lower" format={(v) => v.toFixed(1)} flatWithin={0.2} />} />)
  }
  if (a?.restless_moments != null) {
    tiles.push(<MetricTile key="rest" label="Restless" value={Math.round(a.restless_moments)} chip={<Delta value={p?.restless_moments != null ? a.restless_moments - p.restless_moments : null} better="lower" flatWithin={1} />} />)
  }
  if (!tiles.length) return null
  return <div className="mt-grid">{tiles}</div>
}

function SleepTrend({ nights, need, period }: { nights: Array<Pick<SleepNight, 'date' | 'sleep_s'>>; need: number | null; period: Period }) {
  const points = bucket(nights.map((n) => ({ date: n.date, value: n.sleep_s != null ? n.sleep_s / 3600 : null })), period.freq, 'mean')
  if (points.filter((p) => p.value != null).length < (period.freq === 'day' ? 3 : 2)) return null
  const h = (v: number) => `${Math.floor(v)}:${String(Math.round((v % 1) * 60)).padStart(2, '0')}`
  const band = need ? { low: need / 3600 - 0.5, high: need / 3600 + 0.5, label: 'your need' } : null
  return (
    <section className="card">
      <ChartFrame
        title={period.freq === 'day' ? 'Sleep per night' : `Sleep per night · ${FREQ_WORD[period.freq]} average`}
        caption={<>{need ? `Shaded band = within 30 min of the ${h(need / 3600)} h you need.` : 'Dashed line = your average.'}<span className="block">{periodCaption(period)}</span></>}
      >
        <MetricChart data={points} format={h} color="var(--sleep)" height={180} band={band} freq={period.freq} />
      </ChartFrame>
    </section>
  )
}

function SleepVsRuns({ s }: { s: HealthSleep }) {
  const v = s.sleep_vs_runs
  if (!v) return null
  const a = v.short.easy_hr
  const b = v.long.easy_hr
  const max = Math.max(a ?? 0, b ?? 0)
  const min = Math.min(a ?? Infinity, b ?? Infinity)
  const h = (x: number) => `${Math.max(20, 100 - ((max - x) / Math.max(1, max - min)) * 40)}%`
  return (
    <section className="card">
      <CardHead title="How sleep shows up in your runs" sub="Heart rate at easy pace, the day after" />
      {v.enough_data && a != null && b != null ? (
        <div className="vs-bars" role="img" aria-label={v.sentence ?? ''}>
          <div className="vs-bar">
            <b>{Math.round(a)} bpm</b>
            <span className="bar" style={{ height: h(a), background: 'var(--sleep-tint)', border: '2px solid var(--sleep)' }} />
            <small>under {v.short_h} h (n={v.short.n})</small>
          </div>
          <div className="vs-bar">
            <b>{Math.round(b)} bpm</b>
            <span className="bar" style={{ height: h(b), background: 'var(--sleep)' }} />
            <small>{v.long_h} h + (n={v.long.n})</small>
          </div>
        </div>
      ) : null}
      <p className="chart-caption" style={{ marginTop: 8 }}>
        {v.sentence || `Needs at least 3 easy runs after short (< ${v.short_h} h) and long (${v.long_h} h+) nights to compare.`}
      </p>
    </section>
  )
}

function Tonight({ s }: { s: HealthSleep }) {
  const t = s.tonight
  // The wake planner (R12) gives tonight's bedtime from tomorrow's run; don't repeat it.
  const planned = !!useWakePlan().data?.bedtime
  const items: string[] = []
  if (!planned && t?.bedtime && t.need_s) items.push(`In bed by ${clock(t.bedtime)} to get ${hm(t.need_s)}${t.wake_time ? ` before ${clock(t.wake_time)}` : ''}`)
  items.push('Last caffeine before 2 pm, and no alcohol tonight')
  if ((s.regularity?.bedtime_sd_min ?? 0) > 45) items.push('Same bedtime every night helps more than a lie-in')
  return (
    <section className="card">
      <CardHead title="Tonight" />
      <ul className="bullets">
        {items.map((text) => (
          <li key={text} className="bullet is-sleep"><span className="bullet-dot" aria-hidden="true" /><span>{text}</span></li>
        ))}
        <li className="bullet is-sleep">
          <span className="bullet-dot" aria-hidden="true" />
          <span>5 min slow breathing before bed — <Link to={guideHref('breathing')}>open guide</Link></span>
        </li>
      </ul>
    </section>
  )
}
