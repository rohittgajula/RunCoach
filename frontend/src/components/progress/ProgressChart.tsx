import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { pace } from '../../lib/format'
import type { ProgressPoint } from '../../lib/types'
import { TIP, chartTip, num } from '../ChartTip'
import { ChartFrame, DeltaChip } from '../ChartFrame'
import { tickDate, trendOf } from '../chartUtil'

/** Distance colour buckets — the same split as the bucket toggle. */
export const DIST_BUCKETS = [
  { key: 'lt2', max: 2, label: '<2 km', color: 'var(--run-soft)' },
  { key: '2to5', max: 5, label: '2–5 km', color: 'var(--easy-2)' },
  { key: '5to8', max: 8, label: '5–8 km', color: 'var(--run)' },
  { key: '8plus', max: Infinity, label: '8+ km', color: 'var(--run-ink)' },
]
const colorFor = (p: ProgressPoint) =>
  (p.bucket ? DIST_BUCKETS.find((b) => b.key === p.bucket) : DIST_BUCKETS.find((b) => (p.total_km ?? p.run_km ?? 0) < b.max))?.color ?? 'var(--run)'

type DotProps = { cx?: number; cy?: number; payload?: ProgressPoint }
function PaceDot({ cx, cy, payload }: DotProps) {
  if (cx == null || cy == null || !payload || payload.pace == null) return null
  return <circle cx={cx} cy={cy} r={4.5} fill={colorFor(payload)} stroke="var(--card)" strokeWidth={1.5} />
}

/** Pace (left, faster = up) and avg HR (right) per run; dots coloured by distance. */
export function ProgressChart({ series, height = 240 }: { series: ProgressPoint[]; height?: number }) {
  const data = series.filter((p) => p.pace != null || p.avg_hr != null)
  if (data.length < 2) return <p className="muted small">Two or more runs needed for a chart.</p>
  const paceTrend = trendOf(data.map((p) => p.pace), 'lower', 2)
  const hrTrend = trendOf(data.map((p) => p.avg_hr), null, 1)
  const caption = paceTrend
    ? `${paceTrend.tone === 'flat' ? 'Pace about the same' : `Pace ${Math.round(Math.abs(paceTrend.delta))} s/km ${paceTrend.delta < 0 ? 'faster' : 'slower'}`} in the later half of these runs${hrTrend && hrTrend.tone !== 'flat' ? `, avg HR ${hrTrend.delta > 0 ? '+' : '−'}${Math.round(Math.abs(hrTrend.delta))} bpm` : ''}.`
    : null
  const Tip = chartTip((items, label) => {
    const point = items[0]?.payload as ProgressPoint | undefined
    const lines = []
    if (point?.pace != null) lines.push({ text: `${pace(point.pace)} /km`, color: colorFor(point) })
    if (point?.avg_hr != null) lines.push({ text: `${Math.round(num(point.avg_hr))} bpm`, color: 'var(--hard)' })
    const km = point?.total_km ?? point?.run_km
    return { title: `${tickDate(label)}${km != null ? ` · ${km.toFixed(1)} km` : ''}`, lines }
  })
  return (
    <ChartFrame
      title="Pace & heart rate"
      chip={<DeltaChip trend={paceTrend} format={(v) => `${Math.round(v)} s/km`} label="pace, later half vs earlier half" />}
      caption={caption}
    >
      <div className="chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 48, right: 0, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 4" />
            <XAxis dataKey="date" tickFormatter={tickDate} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={28} />
            <YAxis yAxisId="pace" reversed tickFormatter={(v: number) => pace(v)} axisLine={false} tickLine={false} width={42} domain={['auto', 'auto']} tickCount={4} />
            <YAxis yAxisId="hr" orientation="right" axisLine={false} tickLine={false} width={30} domain={[(min: number) => Math.floor(min - 8), (max: number) => Math.ceil(max + 8)]} tickCount={4} allowDecimals={false} />
            <Tooltip content={Tip} cursor={{ stroke: 'var(--faint)', strokeDasharray: '3 3' }} {...TIP} />
            <Line yAxisId="hr" dataKey="avg_hr" name="hr" stroke="var(--hard)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} connectNulls isAnimationActive={false} />
            <Line yAxisId="pace" dataKey="pace" name="pace" stroke="var(--faint)" strokeWidth={1.5} dot={<PaceDot />} activeDot={{ r: 6 }} connectNulls isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="legend progress-legend">
        {DIST_BUCKETS.map((b) => (
          <span key={b.label}><i className="legend-dot" style={{ background: b.color }} />{b.label}</span>
        ))}
        <span><i className="legend-dash" />Avg HR</span>
      </p>
    </ChartFrame>
  )
}
