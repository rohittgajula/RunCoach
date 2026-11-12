/**
 * The selected runs' traces on one chart, overlaid.
 *
 * The comparison table says the pace fell by 2%. This says *where* — whether
 * the whole run was slower, or the first half matched and it fell apart at
 * twelve minutes. Those are different problems with different answers, and no
 * table can tell them apart.
 *
 * **The x-axis is distance, not elapsed time.** Comparing two runs by the clock
 * puts one runner at 1.0 km and the other at 1.2 km at the same point on the
 * axis, so every vertical comparison is between two different places in the
 * run. By distance, "how did I feel at 1 km" is the same question in both
 * traces — which is the question being asked.
 *
 * Deliberately one metric at a time. Four overlaid runs across three stacked
 * metrics is twelve lines, and twelve lines is a picture of nothing.
 */

import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../../lib/auth'
import { Skeleton } from '../States'

type Point = {
  t: number
  km: number
  pace: number | null
  hr: number | null
  cadence: number | null
}

type Series = { points: Point[]; has_hr: boolean; has_cadence: boolean }

type Metric = 'pace' | 'hr' | 'cadence'

const METRICS: { key: Metric; label: string; unit: string; reversed: boolean }[] = [
  { key: 'pace', label: 'Pace', unit: '/km', reversed: true },
  { key: 'hr', label: 'Heart rate', unit: 'bpm', reversed: false },
  { key: 'cadence', label: 'Cadence', unit: 'spm', reversed: false },
]

/** Four lines that stay apart in both themes and for the common colour blindness. */
const COLOURS = ['var(--run)', 'var(--habits)', 'var(--ok)', 'var(--extra)']

const clock = (seconds: number) => {
  const whole = Math.max(0, Math.round(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/**
 * Resample each run onto a shared distance grid.
 *
 * Recharts needs one row per x value with a column per series; the raw series
 * are per-second and never share a distance. Binning to 100 m is coarse enough
 * that two runs line up and fine enough that a fade inside one kilometre still
 * shows.
 */
function merge(runs: { id: number; label: string; points: Point[] }[], metric: Metric) {
  const BIN_KM = 0.1
  const rows = new Map<number, Record<string, number | null>>()

  for (const run of runs) {
    const buckets = new Map<number, number[]>()
    for (const point of run.points) {
      const value = point[metric]
      if (value == null || !point.km) continue
      const bin = Math.round(point.km / BIN_KM) * BIN_KM
      const list = buckets.get(bin) ?? []
      list.push(value)
      buckets.set(bin, list)
    }
    for (const [bin, values] of buckets) {
      const key = Number(bin.toFixed(1))
      const row = rows.get(key) ?? { km: key }
      row[`r${run.id}`] = values.reduce((a, b) => a + b, 0) / values.length
      rows.set(key, row)
    }
  }
  return [...rows.values()].sort((a, b) => (a.km as number) - (b.km as number))
}

export function CompareChart({
  activities,
}: { activities: { id: number; date: string }[] }) {
  const [metric, setMetric] = useState<Metric>('pace')

  const results = useQueries({
    queries: activities.map((a) => ({
      queryKey: ['activity-series', String(a.id)],
      queryFn: () => api<Series>(`/activities/${a.id}/series/`),
    })),
  })

  if (results.some((r) => r.isPending)) {
    return <div className="cmp-chart"><Skeleton lines={6} /></div>
  }

  const runs = activities
    .map((a, i) => ({
      id: a.id,
      label: new Date(`${a.date}T00:00:00`).toLocaleDateString(undefined,
        { day: 'numeric', month: 'short' }),
      points: results[i].data?.points ?? [],
    }))
    .filter((r) => r.points.length > 0)

  if (runs.length < 2) {
    return (
      <p className="small muted cmp-chart-none">
        Per-second data is needed to draw these, and at least one of the selected
        runs does not have it.
      </p>
    )
  }

  const available = METRICS.filter((m) =>
    runs.some((run) => run.points.some((p) => p[m.key] != null)),
  )
  const active = available.find((m) => m.key === metric) ?? available[0]
  if (!active) return null

  const data = merge(runs, active.key)
  const format = (value: number) =>
    active.key === 'pace' ? clock(value) : String(Math.round(value))

  return (
    <div className="cmp-chart">
      <div className="cmp-chart-head">
        <div className="cmp-metrics">
          {available.map((m) => (
            <button
              key={m.key}
              type="button"
              className={`chip-btn ${m.key === active.key ? 'on' : ''}`}
              onClick={() => setMetric(m.key)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <span className="small muted">by distance, so the same point is the same place</span>
      </div>

      <ResponsiveContainer width="100%" height={230} debounce={0}>
        <LineChart data={data} margin={{ top: 8, right: 6, bottom: 0, left: 2 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis
            dataKey="km" type="number" domain={['dataMin', 'dataMax']}
            tickFormatter={(v) => `${Number(v).toFixed(1)}`}
            tick={{ fontSize: 10, fill: 'var(--axis)' }}
            axisLine={false} tickLine={false} minTickGap={26}
            label={{ value: 'km', position: 'insideBottomRight', offset: -2,
                     fill: 'var(--faint)', fontSize: 10 }}
          />
          <YAxis
            orientation="right" reversed={active.reversed}
            domain={['dataMin', 'dataMax']} tickFormatter={format}
            tick={{ fontSize: 10, fill: 'var(--axis)' }}
            axisLine={false} tickLine={false} width={46}
          />
          <Tooltip
            isAnimationActive={false}
            contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)',
                            borderRadius: 10, fontSize: 12 }}
            labelFormatter={(v) => `at ${Number(v).toFixed(1)} km`}
            formatter={(value, name) => [
              `${format(Number(value))}${active.unit ? ` ${active.unit}` : ''}`, name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
          {runs.map((run, i) => (
            <Line
              key={run.id}
              type="monotone"
              dataKey={`r${run.id}`}
              name={run.label}
              stroke={COLOURS[i % COLOURS.length]}
              strokeWidth={2}
              dot={false}
              // Gaps are gaps: a walk break has no running pace, and joining
              // across it would draw a line through something that did not
              // happen.
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
