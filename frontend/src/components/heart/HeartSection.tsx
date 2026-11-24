import { useMemo, useState } from 'react'
import { ExcludedNote } from '../quality/ReviewEntry'
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { pace } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { type HeartResponse, type HeartRun, type HeartTrendPoint } from '../../lib/r14'
import { useHeart } from '../../lib/r14health'
import { TIP, chartTip } from '../ChartTip'
import { Disclosure, SectionSummary } from '../Disclose'
import { InfoButton } from '../health/InfoButton'
import type { GlossaryKey } from '../health/glossary'
import { useHealthPeriod } from '../health/healthRange'
import { Delta, MetricTile, Pill } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

type MetricKey = 'duration_under_cap_s' | 'hr_at_ref_pace' | 'pace_at_ref_hr' | 'decoupling_pct'

const minutes = (s: number) => {
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

const METRICS: Record<MetricKey, { short: string; fmt: (v: number) => string; reversed?: boolean; info: GlossaryKey }> = {
  duration_under_cap_s: { short: 'Under cap', fmt: minutes, info: 'heart_under_cap' },
  hr_at_ref_pace: { short: 'HR at pace', fmt: (v) => `${Math.round(v)}`, info: 'heart_ref_pace' },
  pace_at_ref_hr: { short: 'Pace at HR', fmt: (v) => pace(v), reversed: true, info: 'heart_ref_hr' },
  decoupling_pct: { short: 'Drift', fmt: (v) => `${v.toFixed(1)} %`, info: 'heart_decoupling' },
}
const KEY_INFO: Record<string, GlossaryKey> = {
  duration_under_cap: 'heart_under_cap', hr_at_ref_pace: 'heart_ref_pace', pace_at_ref_hr: 'heart_ref_hr', decoupling: 'heart_decoupling',
}
const ts = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00`).getTime()
const short = (t: number) => new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

/**
 * R14 §9 Health → More → Heart: "since day 1" in one sentence, every run as a dot with
 * a rolling trend line (hot runs marked, and hideable), and the key numbers with (i).
 */
export function HeartSection() {
  const { period } = useHealthPeriod()
  const q = useHeart(period.params)
  const d = q.data

  if (q.isPending) return <div className="stack"><section className="card"><Skeleton lines={3} /></section><section className="card"><Skeleton height={220} /></section></div>
  if (q.isError && !d) return <ErrorState message={errorText(q.error, 'Heart did not load.')} onRetry={() => q.refetch()} />
  if (!d) return <Empty title="Heart isn’t available yet">Check back after the next update.</Empty>
  if (!d.runs.length) {
    return <Empty title="No runs with heart rate in this range">Run with your watch and sync — each run adds a dot here. Try a longer range.</Empty>
  }
  return (
    <div className={`stack ${q.isPlaceholderData ? 'is-stale' : ''}`}>
      <SectionSummary
        title={d.headline || 'How your heart is adapting'}
        facts={(d.since_day1?.sentences ?? d.sentences).slice(d.headline ? 1 : 0, 3)}
      />
      <HeartChart d={d} />
      <KeyNumbers d={d} />
      <WhatThisCannotTell />
      {(d.heat?.sentence || d.sentences.length > 0) && (
        <Disclosure id="heart-more" title="Heat & what else changed" sub={d.heat?.sentence ?? d.sentences[0]}>
          {d.heat && <HeatCard d={d} />}
          {d.sentences.length > 0 && (
            <section className="card">
              <ul className="bullets">{d.sentences.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </section>
          )}
        </Disclosure>
      )}
      <p className="muted small">
        Reference: {d.ref_hr} bpm ±{d.ref_hr_band} · {pace(d.ref_pace_s_per_km)} /km ±{d.ref_pace_band_s} s. Steady running only — warm-ups and walks left out.
        {d.weather_pending && ' Run weather is still being fetched — hot-run marks may change.'}
      </p>
      {d.caveat && <p className="muted small">{d.caveat}</p>}
    </div>
  )
}

function HeartChart({ d }: { d: HeartResponse }) {
  const [metric, setMetric] = useState<MetricKey>('duration_under_cap_s')
  const [hideHot, setHideHot] = useState(false)
  const m = METRICS[metric]
  const hotCount = d.runs.filter((r) => r.hot).length

  const { dots, hot, line } = useMemo(() => {
    const val = (r: HeartRun) => r[metric]
    const keep = d.runs.filter((r) => val(r) != null)
    const cool = keep.filter((r) => !r.hot).map((r) => ({ t: ts(r.date), v: val(r) as number, run: r }))
    const hotRuns = keep.filter((r) => r.hot).map((r) => ({ t: ts(r.date), v: val(r) as number, run: r }))
    const series: HeartTrendPoint[] = hideHot ? d.trend_cool : d.trend
    const tl = series.filter((p) => p[metric] != null).map((p) => ({ t: ts(p.date), trend: p[metric] as number }))
    return { dots: cool, hot: hotRuns, line: tl }
  }, [d, metric, hideHot])

  const Tip = chartTip((items) => {
    const p = items[0]?.payload as { t: number; v?: number; trend?: number; run?: HeartRun } | undefined
    if (!p) return null
    if (p.run) {
      return {
        title: short(p.t),
        lines: [
          { text: `${m.short}: ${m.fmt(p.v!)}`, color: p.run.hot ? 'var(--fuel)' : 'var(--recovery)' },
          ...(p.run.feels_like_c != null ? [{ text: `Feels like ${Math.round(p.run.feels_like_c)}°${p.run.hot ? ' · hot' : ''}` }] : []),
          ...(p.run.hilly ? [{ text: 'Hilly' }] : []),
        ],
      }
    }
    return p.trend != null ? { title: short(p.t), lines: [{ text: `7-run trend: ${m.fmt(p.trend)}`, color: 'var(--fg)' }] } : null
  })

  return (
    <section className="card stack-sm">
      <div className="ci-chips" role="radiogroup" aria-label="What to chart">
        {(Object.keys(METRICS) as MetricKey[]).map((k) => (
          <button key={k} type="button" role="radio" aria-checked={metric === k} className={`ci-chip ${metric === k ? 'is-on' : ''}`} onClick={() => setMetric(k)}>
            {METRICS[k].short}
          </button>
        ))}
      </div>
      <div className="chart" style={{ height: 230 }} role="img" aria-label={`${m.short} for each run, with a 7-run trend line`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 16, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 4" />
            <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tickFormatter={short} axisLine={false} tickLine={false} minTickGap={36} />
            <YAxis dataKey="v" orientation="right" reversed={!!m.reversed} tickFormatter={m.fmt} axisLine={false} tickLine={false} width={46} domain={['auto', 'auto']} tickCount={4} />
            <Tooltip content={<Tip />} {...TIP} />
            <Scatter name="Runs" data={dots} dataKey="v" fill="var(--recovery)" fillOpacity={0.55} isAnimationActive={false} />
            {!hideHot && <Scatter name="Hot runs" data={hot} dataKey="v" fill="var(--fuel)" shape="diamond" isAnimationActive={false} />}
            <Line name="Trend" data={line} dataKey="trend" type="monotone" stroke="var(--fg)" strokeWidth={2.5} dot={false} isAnimationActive={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-key">
        <span><i className="key-band" style={{ background: 'var(--recovery)', borderRadius: '50%', width: 10 }} />Run</span>
        {!hideHot && hotCount > 0 && <span><i className="key-band" style={{ background: 'var(--fuel)', transform: 'rotate(45deg) scale(0.8)', width: 10 }} />Hot run</span>}
        <span><i className="key-band" style={{ background: 'var(--fg)', height: 3, width: 16 }} />7-run trend</span>
        {metric === 'duration_under_cap_s' && <span>min:sec</span>}
      </div>
      <ExcludedNote />
      {hotCount > 0 && (
        <div className="switch-row">
          <span className="grow">
            <strong className="title-info">Hide hot runs<InfoButton k="heart_hot" /></strong>
            <span className="muted small block">{hotCount} of {d.runs.length} runs felt like {d.hot_threshold_c} °C or more</span>
          </span>
          <button type="button" role="switch" aria-checked={hideHot} aria-label="Hide hot runs" className={`switch ${hideHot ? 'is-on' : ''}`} onClick={() => setHideHot(!hideHot)} />
        </div>
      )}
    </section>
  )
}

/** Size of a key-number change, in that number's own unit. */
function changeFmt(key: string): (v: number) => string {
  if (key === 'duration_under_cap') return (v) => `${Math.round(v / 60)} min`
  if (key === 'pace_at_ref_hr') return (v) => `${Math.round(v)} s/km`
  if (key === 'decoupling') return (v) => `${v.toFixed(1)} %`
  return (v) => `${Math.round(v)} bpm`
}

function KeyNumbers({ d }: { d: HeartResponse }) {
  // HR recovery: median of the last 3 runs that have it (shown with the four from the server).
  const rec = d.runs.map((r) => r.hr_recovery_bpm).filter((v): v is number => v != null).slice(-3).sort((a, b) => a - b)
  const recovery = rec.length ? rec[Math.floor(rec.length / 2)] : null
  return (
    <div className="mt-grid">
      {d.key_numbers.map((k) => (
        <MetricTile
          key={k.key}
          label={k.label}
          value={k.display ?? '—'}
          info={<InfoButton k={KEY_INFO[k.key] ?? 'heart_efficiency'} normal={k.info || undefined} />}
          chip={k.change != null && k.change !== 0 && k.better != null
            ? <Delta value={k.change} better={(k.change > 0) === k.better ? 'higher' : 'lower'} format={changeFmt(k.key)} />
            : undefined}
          sub={k.change != null ? 'vs your first runs' : undefined}
        />
      ))}
      {recovery != null && (
        <MetricTile label="HR recovery" value={recovery} unit="bpm" info={<InfoButton k="heart_recovery" />} sub="drop in 60 s · last 3 runs" />
      )}
    </div>
  )
}

function HeatCard({ d }: { d: HeartResponse }) {
  const h = d.heat!
  return (
    <section className="card stack-sm">
      <div className="kit-head">
        <span className="grow kit-title title-info">Heat<InfoButton k="heart_hot" /></span>
        <Pill topic="fuel">{h.hot_runs} hot · {h.cool_runs} cool</Pill>
      </div>
      {h.sentence && <p className="small">{h.sentence}</p>}
      {h.hot_vs_cool && (
        <p className="muted small">At the same pace: hot runs {Math.round(h.hot_vs_cool.hot_avg)} bpm (n={h.hot_vs_cool.n_hot}) vs cool {Math.round(h.hot_vs_cool.cool_avg)} bpm (n={h.hot_vs_cool.n_cool}).</p>
      )}
      {h.adaptation && (
        <p className="muted small">Hot runs then {Math.round(h.adaptation.early_hot_avg)} bpm → now {Math.round(h.adaptation.recent_hot_avg)} bpm (n={h.adaptation.n_early} / {h.adaptation.n_recent}).</p>
      )}
    </section>
  )
}


/**
 * What this page is, and what it is not.
 *
 * Rohit asked for an analyser that would look at heart-rate irregularities and
 * spot heart disease. This page cannot do that and neither can anything else
 * built on this data, which is worth saying plainly on the page rather than
 * leaving him to assume otherwise.
 *
 * A running watch measures heart rate optically at the wrist: it averages, it
 * loses beats under motion, and it sometimes locks onto cadence instead of
 * pulse. Arrhythmias live in the electrical signal, which needs an ECG. Some
 * Garmin watches have an ECG app, and that — or a doctor with a 12-lead — is
 * the tool for that question.
 *
 * The honest danger is not a missing feature, it is a false reassurance: an
 * app that said "your heart looks fine" from this data would be believed.
 */
function WhatThisCannotTell() {
  return (
    <section className="card stack-sm">
      <strong>What this can and cannot tell you</strong>
      <p className="small muted">
        These are training numbers: how your heart responds to running, and
        whether that response is improving. A rising resting heart rate is
        flagged in your morning check-in, and the drift and pace-at-heart-rate
        figures above show whether you are getting fitter at the same effort.
      </p>
      <p className="small muted">
        None of it is a heart check. Your watch reads your pulse optically at
        the wrist — it averages, it drops beats while you move, and it cannot
        see the electrical signal that rhythm problems show up in. That needs
        an ECG, which some Garmin watches have as a separate app, or a doctor.
        If something feels wrong — chest pain, fainting, a racing or irregular
        pulse at rest — see a doctor and do not wait for a trend here.
      </p>
    </section>
  )
}
