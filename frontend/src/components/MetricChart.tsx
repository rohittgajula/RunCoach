import { useId } from 'react'
import { Area, AreaChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { TIP, chartTip, num } from './ChartTip'
import { monthTicks, tickDate } from './chartUtil'
import { tickFor, ticksFor, tipFor, type Freq } from './health/healthRange'

export type Point = { date: string; value: number | null }

/**
 * Single blue line with a gradient fill — the RestOrTrain chart. `reversed` for
 * paces (faster = higher). `step` draws the value held until the next entry, which is
 * how a weight or threshold reading actually behaves.
 */
export function MetricChart({
  data, format = (v) => String(Math.round(v)), reversed = false, height = 240,
  axis = 'right', step = false, domain, band, average = true, color = 'var(--run)', freq,
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
  /** Topic colour (R10: colour by topic, never good/bad). */
  color?: string
  /** R12: bucket size of `data` — sets the x labels ("Sep 14" weekly, "Oct" monthly). */
  freq?: Freq
}) {
  const gradient = useId().replace(/:/g, '')
  const dates = data.map((d) => d.date)
  const ticks = freq ? ticksFor(dates, freq) : monthTicks(dates)
  const tick = freq ? tickFor(freq) : tickDate
  const tipTitle = freq ? tipFor(freq) : tickDate
  const values = data.map((d) => d.value).filter((v): v is number => v != null && Number.isFinite(v))
  const avg = average && values.length >= 3 ? values.reduce((a, b) => a + b, 0) / values.length : null
  const Tip = chartTip((items, label) => ({ title: tipTitle(label), lines: [{ text: format(num(items[0]?.value)), color }] }))
  const showKey = avg != null || !!band?.label
  return (
    <div className="metric-chart">
    {showKey && (
      <div className="chart-key">
        {band?.label && <span><i className="key-band" style={{ background: color, opacity: 0.25 }} />{band.label}</span>}
        {avg != null && <span><i className="key-avg" />avg {format(avg)}</span>}
      </div>
    )}
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 36, right: axis === 'right' ? 4 : 0, left: axis === 'left' ? 4 : 0, bottom: 0 }}>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.16} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 4" />
          {band && (
            <ReferenceArea
              y1={band.low}
              y2={band.high}
              fill={color}
              fillOpacity={0.12}
              stroke="none"
              ifOverflow="extendDomain"
            />
          )}
          <XAxis
            dataKey="date"
            ticks={ticks}
            tickFormatter={tick}
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
            width={38}
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
            />
          )}
          <Tooltip content={Tip} cursor={{ stroke: 'var(--faint)', strokeDasharray: '3 3' }} {...TIP} />
          <Area
            type={step ? 'stepAfter' : 'monotone'}
            dataKey="value"
            stroke={color}
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill={`url(#${gradient})`}
            connectNulls
            dot={freq && freq !== 'day' && data.length <= 16 ? { r: 3, fill: color, strokeWidth: 0 } : false}
            activeDot={{ r: 5, fill: 'var(--card)', stroke: color, strokeWidth: 3 }}
            baseValue={reversed ? 'dataMax' : 'dataMin'}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
    </div>
  )
}
