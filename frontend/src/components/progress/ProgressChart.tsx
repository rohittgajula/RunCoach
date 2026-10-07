import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { pace } from '../../lib/format'
import type { ProgressPoint } from '../../lib/types'
import { tickDate } from '../chartUtil'

/** Distance colour buckets — the same split as the bucket toggle. */
export const DIST_BUCKETS = [
  { key: 'lt2', max: 2, label: '<2 km', color: '#9ccbff' },
  { key: '2to5', max: 5, label: '2–5 km', color: '#5aa6ff' },
  { key: '5to8', max: 8, label: '5–8 km', color: '#1f7ae0' },
  { key: '8plus', max: Infinity, label: '8+ km', color: '#8d6be8' },
]
const colorFor = (p: ProgressPoint) =>
  (p.bucket ? DIST_BUCKETS.find((b) => b.key === p.bucket) : DIST_BUCKETS.find((b) => (p.total_km ?? p.run_km ?? 0) < b.max))?.color ?? '#1f7ae0'

type DotProps = { cx?: number; cy?: number; payload?: ProgressPoint }
function PaceDot({ cx, cy, payload }: DotProps) {
  if (cx == null || cy == null || !payload || payload.pace == null) return null
  return <circle cx={cx} cy={cy} r={4.5} fill={colorFor(payload)} stroke="var(--card)" strokeWidth={1.5} />
}

/** Pace (left, faster = up) and avg HR (right) per run; dots coloured by distance. */
export function ProgressChart({ series, height = 240 }: { series: ProgressPoint[]; height?: number }) {
  const data = series.filter((p) => p.pace != null || p.avg_hr != null)
  if (data.length < 2) return <p className="muted small">Two or more runs needed for a chart.</p>
  return (
    <>
      <div className="chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="date" tickFormatter={tickDate} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={28} />
            <YAxis yAxisId="pace" reversed tickFormatter={(v: number) => pace(v)} axisLine={false} tickLine={false} width={48} domain={['auto', 'auto']} tickCount={4} />
            <YAxis yAxisId="hr" orientation="right" axisLine={false} tickLine={false} width={34} domain={[(min: number) => Math.floor(min - 8), (max: number) => Math.ceil(max + 8)]} tickCount={4} allowDecimals={false} />
            <Tooltip
              labelFormatter={(label) => tickDate(String(label))}
              formatter={(value, name) => (name === 'pace' ? [`${pace(Number(value))} /km`, 'Pace'] : [`${value} bpm`, 'Avg HR'])}
            />
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
    </>
  )
}
