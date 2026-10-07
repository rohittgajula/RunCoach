import { useMemo, useState } from 'react'
import { errorText, useCompare, useCompareMetrics } from '../../lib/queries'
import type { CompareMetric, CompareResult } from '../../lib/types'
import { CardHead, ToneChip } from '../Kit'
import { RangeSwitch } from '../RangeSwitch'
import { Empty, ErrorState, Skeleton } from '../States'

const RANGES = [
  { value: '4w', label: '4w' },
  { value: '3m', label: '3m' },
  { value: '6m', label: '6m' },
  { value: '1y', label: '1y' },
]
const LAGS = [
  { value: '0', label: 'Same day' },
  { value: '1', label: 'Next day' },
]
const GROUP: Record<string, string> = { wellness: 'Body & sleep', day: 'Your day', habits: 'Habits', runs: 'Runs' }
const ORDER = ['wellness', 'day', 'runs', 'habits']

const fmt = (v: number) => (Math.abs(v) >= 100 ? Math.round(v).toString() : Math.abs(v) >= 10 ? v.toFixed(1).replace(/\.0$/, '') : v.toFixed(2).replace(/0$/, ''))

function Picker({ label, value, onChange, metrics, other }: { label: string; value: string; onChange: (v: string) => void; metrics: CompareMetric[]; other: string }) {
  // Known groups first, then anything newer the catalogue adds (R11 adds day metrics).
  const names = [...ORDER, ...new Set(metrics.map((m) => m.group).filter((g) => !ORDER.includes(g)))]
  const groups = names.map((g) => [g, metrics.filter((m) => m.group === g)] as const).filter(([, list]) => list.length)
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {groups.map(([g, list]) => (
          <optgroup key={g} label={GROUP[g] ?? g}>
            {list.map((m) => <option key={m.key} value={m.key} disabled={m.key === other}>{m.key === 'private' ? '🌙 Private' : m.label}</option>)}
          </optgroup>
        ))}
      </select>
    </label>
  )
}

/** Health → Compare any two: two pickers, scatter + trend line, one plain sentence. */
export function CompareSection() {
  const catalogue = useCompareMetrics()
  const metrics = useMemo(() => catalogue.data?.metrics ?? [], [catalogue.data])
  const has = (k: string) => metrics.some((m) => m.key === k)
  const [x, setX] = useState('')
  const [y, setY] = useState('')
  const [range, setRange] = useState('3m')
  const [lag, setLag] = useState<'0' | '1'>('1')
  const xKey = x || (has('sleep_h') ? 'sleep_h' : metrics[0]?.key ?? '')
  const yKey = y || (has('easy_hr') ? 'easy_hr' : metrics.find((m) => m.key !== xKey)?.key ?? '')
  const result = useCompare(xKey, yKey, range, lag === '1' ? 1 : 0)

  if (catalogue.isPending) return <section className="card"><Skeleton lines={4} /></section>
  if (!metrics.length) return <Empty title="Compare isn’t available yet">Sync some days of data and check back.</Empty>

  return (
    <div className="stack">
      <section className="card stack">
        <CardHead title="Compare any two" sub="Do two things move together? Pick any pair." />
        <div className="picker-row">
          <Picker label="This" value={xKey} onChange={setX} metrics={metrics} other={yKey} />
          <Picker label="Against" value={yKey} onChange={setY} metrics={metrics} other={xKey} />
        </div>
        <div className="row-wrap">
          <RangeSwitch compact value={range} onChange={setRange} options={RANGES} label="Range" />
          <RangeSwitch compact value={lag} onChange={(v) => setLag(v as '0' | '1')} options={LAGS} label="Timing" />
        </div>
      </section>

      {result.isPending && <section className="card"><Skeleton height={240} /></section>}
      {result.isError && !result.data && <ErrorState message={errorText(result.error)} onRetry={() => result.refetch()} />}
      {result.data && <CompareResultCard r={result.data} stale={result.isPlaceholderData} />}
    </div>
  )
}

function CompareResultCard({ r, stale }: { r: CompareResult; stale: boolean }) {
  return (
    <section className={`card stack ${stale ? 'is-stale' : ''}`}>
      <p className="compare-sentence">{r.sentence}</p>
      <div className="row-wrap">
        {r.rho != null && <ToneChip tone="info">ρ = {r.rho.toFixed(2)}</ToneChip>}
        <ToneChip>n = {r.n}</ToneChip>
        {r.strength && <ToneChip>{r.strength === 'none' ? 'no clear link' : `${r.strength} link`}</ToneChip>}
      </div>
      {r.points.length >= 2 ? <Scatter r={r} /> : <p className="muted small">Not enough days with both values yet.</p>}
      <p className="chart-caption">
        Each dot is one {r.lag ? 'day (y = the day after)' : 'day'}. {r.trend ? 'Line = overall trend. ' : ''}{r.caveat}
      </p>
    </section>
  )
}

function Scatter({ r }: { r: CompareResult }) {
  const W = 320
  const H = 220
  const pad = { l: 36, r: 10, t: 10, b: 30 }
  const xs = r.points.map((p) => p.x)
  const ys = r.points.map((p) => p.y)
  const padOf = (lo: number, hi: number) => (hi - lo || Math.abs(hi) || 1) * 0.06
  const [x0, x1] = [Math.min(...xs) - padOf(Math.min(...xs), Math.max(...xs)), Math.max(...xs) + padOf(Math.min(...xs), Math.max(...xs))]
  const [y0, y1] = [Math.min(...ys) - padOf(Math.min(...ys), Math.max(...ys)), Math.max(...ys) + padOf(Math.min(...ys), Math.max(...ys))]
  const sx = (v: number) => pad.l + ((v - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r)
  const sy = (v: number) => H - pad.b - ((v - y0) / (y1 - y0 || 1)) * (H - pad.t - pad.b)
  const t = r.trend
  const unit = (u: string) => (u ? ` (${u})` : '')
  return (
    <div className="scatter-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Scatter of ${r.x.label} against ${r.y.label}, ${r.n} days`}>
        <defs>
          <clipPath id="cmp-plot"><rect x={pad.l} y={pad.t} width={W - pad.l - pad.r} height={H - pad.t - pad.b} /></clipPath>
        </defs>
        <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke="var(--line)" />
        <line x1={pad.l} y1={pad.t} x2={pad.l} y2={H - pad.b} stroke="var(--line)" />
        <text x={pad.l - 4} y={pad.t + 8} textAnchor="end" className="axis-text">{fmt(y1)}</text>
        <text x={pad.l - 4} y={H - pad.b} textAnchor="end" className="axis-text">{fmt(y0)}</text>
        <text x={pad.l} y={H - pad.b + 14} textAnchor="start" className="axis-text">{fmt(x0)}</text>
        <text x={W - pad.r} y={H - pad.b + 14} textAnchor="end" className="axis-text">{fmt(x1)}</text>
        {r.points.map((p) => (
          <circle key={p.date} cx={sx(p.x)} cy={sy(p.y)} r={4.5} fill="var(--run)" fillOpacity={0.45} stroke="var(--run)" strokeWidth={1}>
            <title>{`${p.date}: ${fmt(p.x)} · ${fmt(p.y)}`}</title>
          </circle>
        ))}
        {t && (
          <line
            clipPath="url(#cmp-plot)"
            x1={sx(x0)} y1={sy(t.slope * x0 + t.intercept)} x2={sx(x1)} y2={sy(t.slope * x1 + t.intercept)}
            stroke="var(--fg)" strokeWidth={2.5} strokeLinecap="round"
          />
        )}
      </svg>
      <div className="scatter-labels">
        <span>→ {r.x.label}{unit(r.x.unit)}</span>
        <span>↑ {r.y.label}{unit(r.y.unit)}{r.lag ? ', next day' : ''}</span>
      </div>
    </div>
  )
}
