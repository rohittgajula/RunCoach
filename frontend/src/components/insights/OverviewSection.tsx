import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { pace } from '../../lib/format'
import { errorText, useInsights } from '../../lib/queries'
import type { Insights } from '../../lib/types'
import { Bullets } from '../Bullets'
import { trendOf, type Trend } from '../chartUtil'
import { bucket, periodCaption, useHealthPeriod, withApiPeriod, type Freq, type Period } from '../health/healthRange'
import { TrainingStatusCard } from '../health/TrainingStatusCard'
import { InjuryCard } from '../injury/InjuryCard'
import { InfoButton } from '../health/InfoButton'
import type { GlossaryKey } from '../health/glossary'
import { ActivityIcon, BandageIcon, ChevronRight, CoachIcon, HealthIcon, ReportIcon, RunIcon, ScatterIcon, SmokeIcon, SparkIcon, SunIcon } from '../Icons'
import { Disclosure, Row, RowGroup, SheetRow } from '../Disclose'
import { GoalChip } from '../goals/GoalChip'
import { Arrow, Delta, MetricTile, TopicRing } from '../Kit'
import { FitnessSheet } from '../profile/FitnessSheet'
import { Sparkline } from '../Sparkline'
import { ErrorState, Skeleton } from '../States'
import { ForecastCard } from '../today/ForecastCard'
import { FocusCard, LoadCard, SummaryCard } from './AdviceCards'
import { InsightChartSheet } from './InsightChartSheet'
import { CHARTS, type ChartKey } from './charts'
import { HabitsTeaser, ProgressTeaser } from './Teasers'

/** The metric's series, bucketed to the chosen frequency (R12). */
const values = (data: Insights, key: ChartKey, freq: Freq = 'day') =>
  bucket(CHARTS[key].points(data), freq, CHARTS[key].agg).map((p) => p.value).filter((v): v is number => v != null && Number.isFinite(v))
const lastOf = (v: number[]) => (v.length ? v[v.length - 1] : null)
const halves = (v: number[]) => {
  if (v.length < 4) return null
  const mid = Math.floor(v.length / 2)
  const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length
  return { before: mean(v.slice(0, mid)), now: mean(v.slice(mid)) }
}

/** Health → Overview: summary + rings, metric tiles, status, what changed, tomorrow, links. */
export function OverviewSection() {
  const { period: chosen } = useHealthPeriod()
  const [chart, setChart] = useState<ChartKey | null>(null)
  const [fitnessOpen, setFitnessOpen] = useState(false)
  const insights = useInsights(chosen.params)
  const data = insights.data
  const period = withApiPeriod(chosen, data?.period)
  const range = chosen.params

  return (
    <>
      {insights.isPending && [0, 1, 2].map((i) => (
        <section key={i} className="card"><Skeleton lines={4} /></section>
      ))}
      {insights.isError && !data && (
        <ErrorState message={errorText(insights.error, 'Health did not load.')} onRetry={() => insights.refetch()} />
      )}

      {data && (
        <div className={`stack ${insights.isPlaceholderData ? 'is-stale' : ''}`}>
          <SummaryHero data={data} freq={period.freq} />
          <GoalChip />
          <Tiles data={data} freq={period.freq} onChart={setChart} />
          <WhatChanged data={data} period={period} />
          {/* R14 §1: everything else one tap away — same cards, in sheets or their sections. */}
          <RowGroup title="More for this period">
            <SheetRow icon={<ActivityIcon size={20} />} title="Training status" sub="Productive, maintaining or overreaching — and why">
              <TrainingStatusCard period={chosen} />
            </SheetRow>
            <SheetRow icon={<SunIcon size={20} />} title="Tomorrow’s readiness" sub="An estimate, and what could raise it">
              <ForecastCard detailed />
            </SheetRow>
            <SheetRow icon={<SparkIcon size={20} />} title="Focus next" sub={data.focus?.[0]?.title ?? 'The one thing to work on'}>
              <FocusCard focus={data.focus ?? []} hasRuns={(data.running?.runs ?? 0) > 0} />
            </SheetRow>
            <SheetRow icon={<RunIcon size={20} />} title="Training load" sub={data.load?.status ? data.load.status.replace(/_/g, ' ') : 'Fitness, fatigue and form'}>
              <LoadCard load={data.load} onOpen={() => setFitnessOpen(true)} />
            </SheetRow>
            <SheetRow icon={<BandageIcon size={20} />} title="Injury watch" sub="Load ramp, pain and form flags">
              <InjuryCard />
            </SheetRow>
            <SheetRow icon={<CoachIcon size={20} />} title="Are you running well?" sub="The coach’s overview in plain words">
              <SummaryCard summary={data.summary} range={range} />
            </SheetRow>
          </RowGroup>
          <RowGroup title="Sections">
            <ProgressTeaser row icon={<RunIcon size={20} />} />
            <HabitsTeaser row icon={<SmokeIcon size={20} />} />
            <Row to="/health/heart" icon={<HealthIcon size={20} />} title="Heart" sub="How your heart is adapting, day by day" />
            <Row to="/health/reports" icon={<ReportIcon size={20} />} title="Weekly reports" sub="Every Monday: runs, recovery and habits" />
            <Row to="/health/compare" icon={<ScatterIcon size={20} />} title="Compare any two" sub="Does one move with the other?" />
          </RowGroup>
        </div>
      )}

      <InsightChartSheet chart={chart} onClose={() => setChart(null)} />
      <FitnessSheet view={fitnessOpen ? 'status' : null} onClose={() => setFitnessOpen(false)} />
    </>
  )
}

export function LinkRow({ to, icon, title, text }: { to: string; icon: ReactNode; title: string; text: string }) {
  return (
    <Link to={to} className="card link-row">
      <span className="link-row-icon">{icon}</span>
      <span className="grow">
        <span className="link-row-title">{title}</span>
        <span className="link-row-text">{text}</span>
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}

function SummaryHero({ data, freq }: { data: Insights; freq: Freq }) {
  const hrv = trendOf(values(data, 'hrv', freq), 'higher')
  const rhr = trendOf(values(data, 'rhr', freq), 'lower')
  const sleep = trendOf(values(data, 'sleep', freq), 'higher', 1 / 6)
  const recovery = [hrv, rhr].filter((t): t is Trend => !!t)
  const good = recovery.filter((t) => t.tone === 'good').length
  const bad = recovery.filter((t) => t.tone === 'bad').length
  const headline = !recovery.length
    ? 'Keep syncing — your trends build up over a few weeks'
    : bad === 0 && good > 0
      ? 'You’re recovering better than earlier in this period'
      : bad > 0 && good === 0
        ? 'Recovery has been under more strain lately'
        : 'Recovery is holding steady'
  const word = (t: Trend | null, name: string, up: string, down: string) =>
    !t ? null : t.tone === 'flat' ? `${name} steady` : `${name} ${t.delta > 0 ? up : down}`
  const sub = [word(hrv, 'HRV', 'up', 'down'), word(rhr, 'resting HR', 'up', 'down'), word(sleep, 'sleep', 'longer', 'shorter')]
    .filter(Boolean).join(', ')

  const sleepScore = trendOf(bucket((data.sleep?.series ?? []).map((p) => ({ date: p.date, value: p.score ?? null })), freq).map((p) => p.value), 'higher')
  const share = values(data, 'run_fraction', freq)
  const shareTrend = trendOf(share, 'higher')
  const rings: Array<{ key: string; g: GlossaryKey; name: string; caption?: string; topic: 'recovery' | 'sleep' | 'run'; value: number | null; trend: Trend | null; better: 'higher' | 'lower' }> = [
    { key: 'r', g: 'readiness', name: 'Readiness', topic: 'recovery', value: data.readiness?.score ?? null, trend: null, better: 'higher' },
    { key: 's', g: 'sleep_score', name: 'Sleep score', topic: 'sleep', value: data.sleep?.avg_score ?? null, trend: sleepScore, better: 'higher' },
    { key: 'f', g: 'run_fraction', name: 'Run vs walk', caption: 'share of time running', topic: 'run', value: lastOf(share), trend: shareTrend, better: 'higher' },
  ]
  const shown = rings.filter((r) => r.value != null)

  return (
    <section className="card hero-summary">
      <p className="hero-summary-title">{headline}</p>
      {sub && <p className="muted small">{sub[0].toUpperCase() + sub.slice(1)}.</p>}
      {shown.length > 0 && (
        <div className="ring-row" style={{ gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))` }}>
          {shown.map((r) => (
            <div key={r.key}>
              <TopicRing value={r.value} topic={r.topic} size={84} label={r.name} />
              <span className="ring-name title-info">{r.name}<InfoButton k={r.g} /></span>
              {r.caption && <span className="ring-caption">{r.caption}</span>}
              {r.trend && r.trend.tone !== 'flat' ? (
                <span className="arrow-line">
                  <Arrow value={r.trend.delta} better={r.better} /> {Math.round(Math.abs(r.trend.delta))}
                </span>
              ) : r.trend ? <span className="arrow-line muted">— steady</span> : null}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function Tiles({ data, freq, onChart }: { data: Insights; freq: Freq; onChart: (k: ChartKey) => void }) {
  type Def = { key: ChartKey; label: string; value: string | null; unit?: string; bars?: boolean }
  const v = (k: ChartKey) => lastOf(values(data, k))
  const sleepAvg = data.sleep?.avg_s ?? null
  const defs: Def[] = [
    { key: 'hrv', label: 'HRV', value: data.hrv?.last_night_ms != null ? String(Math.round(data.hrv.last_night_ms)) : v('hrv') != null ? String(Math.round(v('hrv')!)) : null, unit: 'ms' },
    { key: 'rhr', label: 'Resting HR', value: data.resting_hr?.current != null ? String(Math.round(data.resting_hr.current)) : null, unit: 'bpm' },
    { key: 'sleep', label: 'Sleep', value: sleepAvg ? `${Math.floor(sleepAvg / 3600)}:${String(Math.round((sleepAvg % 3600) / 60)).padStart(2, '0')}` : null, unit: 'h', bars: true },
    { key: 'stress', label: 'Stress', value: data.stress?.avg != null ? String(Math.round(data.stress.avg)) : null },
    { key: 'body_battery', label: 'Body battery', value: data.body_battery?.avg != null ? String(Math.round(data.body_battery.avg)) : null, unit: 'avg' },
    { key: 'vo2max', label: 'VO2max', value: data.vo2max?.value != null ? String(Math.round(data.vo2max.value)) : null },
    { key: 'respiration', label: 'Breathing', value: data.respiration?.sleep_avg_rpm != null ? data.respiration.sleep_avg_rpm.toFixed(1) : null, unit: '/min' },
    { key: 'easy_pace', label: 'Easy pace', value: v('easy_pace') != null ? pace(v('easy_pace')) : null, unit: '/km' },
    { key: 'run_fraction', label: 'Running share', value: v('run_fraction') != null ? String(Math.round(v('run_fraction')!)) : null, unit: '%' },
    { key: 'longest_run', label: 'Longest run', value: v('longest_run') != null ? CHARTS.longest_run.format(v('longest_run')!) : null },
    { key: 'cadence', label: 'Cadence', value: data.running?.cadence.avg != null ? String(Math.round(data.running.cadence.avg)) : null, unit: 'spm' },
  ]
  const shown = defs.filter((d) => d.value != null)
  if (!shown.length) return null
  const tile = (d: Def) => {
    const cfg = CHARTS[d.key]
    const vals = values(data, d.key, freq)
    const t = trendOf(vals, cfg.better)
    const color = `var(--${cfg.topic ?? 'run'})`
    const gk: GlossaryKey = d.key === 'respiration' ? 'breathing_rate' : d.key
    const band = cfg.band?.(data)
    const normal = d.key === 'hrv' && band ? `${cfg.format(band.low)}–${cfg.format(band.high)} ms (your baseline)`
      : t ? `${cfg.format(t.avg)}${d.unit && d.unit !== 'avg' ? ` ${d.unit}` : ''} on average this period` : undefined
    return (
      <MetricTile
        key={d.key}
        label={d.label}
        value={d.value}
        unit={d.unit}
        info={<InfoButton k={gk} normal={normal} />}
        onClick={() => onChart(d.key)}
        chip={t ? <Delta value={t.tone === 'flat' ? 0 : t.delta} better={cfg.better} format={cfg.delta ?? cfg.format} steadyText="0" /> : undefined}
      >
        {d.bars && vals.length >= 2 ? (
          <MiniBars values={vals.slice(-7)} color={color} />
        ) : vals.length >= 2 ? (
          <Sparkline values={cfg.reversed ? vals.map((x) => -x) : vals} height={36} color={color} />
        ) : null}
      </MetricTile>
    )
  }
  // R14 §1: four key tiles; the rest behind "All metrics".
  const key = shown.slice(0, 4)
  const rest = shown.slice(4)
  return (
    <>
      <div className="mt-grid">{key.map(tile)}</div>
      {rest.length > 0 && (
        <Disclosure id="overview-metrics" title="All metrics" sub={rest.map((d) => d.label).join(' · ')}>
          <div className="mt-grid">{rest.map(tile)}</div>
        </Disclosure>
      )}
    </>
  )
}

/** Last N values as soft bars, the latest in full colour. */
export function MiniBars({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(...values, 1)
  return (
    <span className="mini-bars" aria-hidden="true">
      {values.map((v, i) => (
        <span key={i} style={{ height: `${Math.max(8, (v / max) * 100)}%`, background: color, opacity: i === values.length - 1 ? 1 : 0.35 }} />
      ))}
    </span>
  )
}

/** "HRV averaged 45 ms, up from 41 ms" — the later half of the range vs the earlier half. */
function WhatChanged({ data, period }: { data: Insights; period: Period }) {
  const [all, setAll] = useState(false)
  const rows: Array<{ tone: string; text: string }> = []
  const add = (key: ChartKey, name: string, fmt: (v: number) => string, unit: string, flat: number) => {
    const h = halves(values(data, key))
    if (!h) return
    const d = h.now - h.before
    const better = CHARTS[key].better
    if (Math.abs(d) <= flat) {
      rows.push({ tone: 'neutral', text: `${name} about the same (${fmt(h.now)}${unit})` })
      return
    }
    const good = better == null ? null : (d > 0) === (better === 'higher')
    const dir = key === 'easy_pace' ? (d < 0 ? 'faster' : 'slower') : d > 0 ? 'up' : 'down'
    rows.push({ tone: good == null ? 'neutral' : good ? 'good' : 'bad', text: `${name} averaged ${fmt(h.now)}${unit}, ${dir} from ${fmt(h.before)}${unit}` })
  }
  add('hrv', 'HRV', (v) => String(Math.round(v)), ' ms', 1)
  add('rhr', 'Resting HR', (v) => String(Math.round(v)), ' bpm', 0.7)
  add('sleep', 'Sleep', (v) => `${Math.floor(v)}h ${String(Math.round((v % 1) * 60)).padStart(2, '0')}m`, '', 1 / 6)
  add('easy_pace', 'Easy pace', (v) => pace(v), ' /km', 3)
  add('stress', 'Stress', (v) => String(Math.round(v)), '', 1.5)
  if (!rows.length) return null
  rows.sort((a, b) => (a.tone === 'good' ? 0 : a.tone === 'bad' ? 1 : 2) - (b.tone === 'good' ? 0 : b.tone === 'bad' ? 1 : 2))
  return (
    <section className="card">
      <h2 className="kit-title" style={{ marginBottom: 10 }}>What changed in this period</h2>
      <Bullets items={all ? rows : rows.slice(0, 3)} />
      {rows.length > 3 && (
        <button type="button" className="see-details" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `${rows.length - 3} more`} <ChevronRight size={16} />
        </button>
      )}
      <p className="chart-caption" style={{ marginTop: 8 }}>{periodCaption(period, { compare: false, freq: false })} · second half vs first half.</p>
    </section>
  )
}
