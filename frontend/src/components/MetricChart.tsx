import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { TIP, chartTip, num } from './ChartTip'
import { monthTicks, tickDate } from './chartUtil'

export type Point = { date: string; value: number | null }

/**
 * Single blue line with a gradient fill — the RestOrTrain chart. `reversed` for
 * paces (faster = higher). `step` draws the value held until the next entry, which is
 * how a weight or threshold reading actually behaves.
 */
export function MetricChart({
  data, format = (v) => String(Math.round(v)), reversed = false, height = 240,
  axis = 'right', step = false, domain, band, average = true,
}: {
  data: Point[]
  format?: (value: number) => string
  reversed?: boolean
  height?: number
  axis?: 'left' | 'right'
  step?: boolean
  domain?: [number | 'auto' | 'dataMin' | 'dataMax', number | 'auto' | 'dataMin' | 'dataMax']
  /** Shaded "normal range" (HRV baseline, cadence target). */
  band?: { low: number; high: number; label?: string } | null
  /** Dashed line at the average of the visible values. */
  average?: boolean
}) {
  const gradient = useId().replace(/:/g, '')
  const ticks = monthTicks(data.map((d) => d.date))
  const values = data.map((d) => d.value).filter((v): v is number => v != null && Number.isFinite(v))
  const avg = average && values.length >= 3 ? values.reduce((a, b) => a + b, 0) / values.length : null
  const Tip = chartTip((items, label) => ({ title: tickDate(label), lines: [{ text: format(num(items[0]?.value)), color: '#1f7ae0' }] }))
  return (
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 44, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#1f7ae0" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#1f7ae0" stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 4" />
          {band && (
            <ReferenceArea
              y1={band.low}
              y2={band.high}
              fill="#2e9d58"
              fillOpacity={0.13}
              stroke="none"
              ifOverflow="extendDomain"
              label={band.label ? { value: band.label, position: 'insideTopLeft', fill: '#2e9d58', fontSize: 12, fontWeight: 600 } : undefined}
            />
          )}
          <XAxis
            dataKey="date"
            ticks={ticks}
            tickFormatter={tickDate}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            orientation={axis}
            reversed={reversed}
            tickFormatter={format}
            axisLine={false}
            tickLine={false}
            width={40}
            mirror
            domain={domain ?? ['auto', 'auto']}
            tickCount={4}
          />
          {avg != null && (
            <ReferenceLine
              y={avg}
              stroke="var(--muted)"
              strokeDasharray="4 4"
              strokeOpacity={0.7}
              ifOverflow="extendDomain"
              label={{ value: `avg ${format(avg)}`, position: axis === 'left' ? 'insideTopRight' : 'insideTopLeft', fill: 'var(--muted)', fontSize: 11 }}
            />
          )}
          <Tooltip content={Tip} cursor={{ stroke: 'var(--faint)', strokeDasharray: '3 3' }} {...TIP} />
          <Area
            type={step ? 'stepAfter' : 'monotone'}
            dataKey="value"
            stroke="#1f7ae0"
            strokeWidth={2.5}
            fill={`url(#${gradient})`}
            connectNulls
            dot={false}
            activeDot={{ r: 5, stroke: 'var(--card)', strokeWidth: 2 }}
            baseValue={reversed ? 'dataMax' : 'dataMin'}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
