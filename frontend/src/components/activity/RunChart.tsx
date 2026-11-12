/**
 * One metric across a single run, with the run/walk blocks shaded behind it.
 *
 * The existing MetricChart plots a value per day. This plots a value per second
 * within one run, which is a different axis and a different question.
 *
 * The shading is the point. Garmin's cadence trace for Rohit's 9 Nov run swings
 * between about 155 and about 100 and averages 108 — the whole run/walk story is
 * visible in it and nothing on the page says so. Here the blocks are drawn from
 * the segmentation, so every trace is read against them: a heart rate that keeps
 * climbing through a walk block means something quite different from one that
 * climbs through a run block, and until the blocks are on the chart you cannot
 * tell which you are looking at.
 *
 * Paces are plotted on a reversed axis, because faster should be higher. A pace
 * chart with 12:00/km above 6:00/km is technically correct and reads backwards
 * to everyone who has ever looked at one.
 */

import {
  Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useId } from 'react'

export type SeriesPoint = {
  t: number
  km: number
  pace: number | null
  hr: number | null
  hr_clean: number | null
  cadence: number | null
  altitude: number | null
}

export type Block = {
  index: number
  kind: 'run' | 'walk' | 'stop'
  start_offset_s: number
  duration_s: number
}

const BLOCK_FILL: Record<string, string> = {
  run: 'var(--run)',
  walk: 'var(--walk)',
  stop: 'transparent',
}

/** mm:ss from seconds — used for both the clock axis and pace values. */
export const clock = (seconds: number): string => {
  const whole = Math.max(0, Math.round(seconds))
  const m = Math.floor(whole / 60)
  const s = whole % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function RunChart({
  points, blocks, metric, label, unit, colour = 'var(--run)',
  reversed = false, format = (v: number) => String(Math.round(v)),
  height = 170, band,
}: {
  points: SeriesPoint[]
  blocks: Block[]
  metric: keyof SeriesPoint
  label: string
  unit?: string
  colour?: string
  reversed?: boolean
  format?: (value: number) => string
  height?: number
  /** A target range worth seeing behind the trace, e.g. a heart-rate zone. */
  band?: { low: number; high: number; label?: string } | null
}) {
  const id = useId().replace(/:/g, '')
  const values = points.map((p) => p[metric]).filter((v): v is number => v != null)

  if (values.length === 0) {
    return (
      <section className="runchart runchart-empty">
        <h3>{label}</h3>
        <p className="small muted">Not recorded on this run.</p>
      </section>
    )
  }

  const average = values.reduce((total, v) => total + v, 0) / values.length
  const last = points[points.length - 1]?.t ?? 0

  return (
    <section className="runchart">
      <div className="runchart-head">
        <h3>{label}</h3>
        <span className="small muted num">
          avg {format(average)}{unit ? ` ${unit}` : ''}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={height} debounce={0}>
        <AreaChart data={points} margin={{ top: 6, right: 4, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colour} stopOpacity={0.35} />
              <stop offset="100%" stopColor={colour} stopOpacity={0.02} />
            </linearGradient>
          </defs>

          {/* The blocks go in first so the trace draws over them. */}
          {blocks.filter((b) => b.kind !== 'stop').map((b) => (
            <ReferenceArea
              key={b.index}
              x1={b.start_offset_s}
              x2={b.start_offset_s + b.duration_s}
              fill={BLOCK_FILL[b.kind]}
              fillOpacity={b.kind === 'run' ? 0.14 : 0.3}
              strokeOpacity={0}
              ifOverflow="extendDomain"
            />
          ))}

          {band && (
            <ReferenceArea
              y1={band.low} y2={band.high}
              fill="var(--ok)" fillOpacity={0.1} strokeOpacity={0}
            />
          )}

          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            dataKey="t"
            type="number"
            domain={[0, last]}
            tickFormatter={clock}
            tick={{ fontSize: 10, fill: 'var(--axis)' }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            orientation="right"
            reversed={reversed}
            domain={['dataMin', 'dataMax']}
            tickFormatter={format}
            tick={{ fontSize: 10, fill: 'var(--axis)' }}
            axisLine={false}
            tickLine={false}
            width={44}
          />
          <ReferenceLine
            y={average}
            stroke="var(--faint)"
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
          />
          <Tooltip
            isAnimationActive={false}
            contentStyle={{
              background: 'var(--card)', border: '1px solid var(--line)',
              borderRadius: 10, fontSize: 12,
            }}
            labelFormatter={(t) => `at ${clock(Number(t))}`}
            formatter={(value) => [
              `${format(Number(value))}${unit ? ` ${unit}` : ''}`, label,
            ]}
          />
          <Area
            type="monotone"
            dataKey={metric as string}
            stroke={colour}
            strokeWidth={2}
            fill={`url(#g${id})`}
            connectNulls={false}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </section>
  )
}

/** The blocks on their own, as a strip. Reads at a glance where the running was. */
export function BlockStrip({ blocks, total }: { blocks: Block[]; total: number }) {
  if (!blocks.length || total <= 0) return null
  return (
    <div className="blockstrip" aria-label="Run and walk blocks">
      {blocks.map((b) => (
        <i
          key={b.index}
          className={`bs-${b.kind}`}
          style={{ width: `${(b.duration_s / total) * 100}%` }}
          title={`${b.kind} · ${clock(b.duration_s)}`}
        />
      ))}
    </div>
  )
}
