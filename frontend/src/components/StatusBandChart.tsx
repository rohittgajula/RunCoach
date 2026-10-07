import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { TIP, chartTip, num } from './ChartTip'
import { monthTicks, tickDate } from './chartUtil'

/**
 * Training status = form (fitness − fatigue) against fixed bands:
 *  Detraining > +20 · Fresh +5…+20 · Maintaining −10…+5 · Gaining Fitness −30…−10 ·
 *  Overtraining Risk < −30. Thresholds are the backend's (SPEC §3).
 */
export const BANDS = [
  { key: 'detraining', label: 'Detraining', from: 20, to: Infinity, fill: 'color-mix(in srgb, var(--habits) 16%, transparent)', text: 'var(--habits-ink)' },
  { key: 'fresh', label: 'Fresh', from: 5, to: 20, fill: 'color-mix(in srgb, var(--run) 13%, transparent)', text: 'var(--run-ink)' },
  { key: 'maintaining', label: 'Maintaining', from: -10, to: 5, fill: 'rgba(140, 140, 160, 0.10)', text: 'var(--muted)' },
  { key: 'gaining', label: 'Gaining Fitness', from: -30, to: -10, fill: 'color-mix(in srgb, var(--ok) 14%, transparent)', text: 'var(--good-fg)' },
  { key: 'overtraining', label: 'Overtraining Risk', from: -Infinity, to: -30, fill: 'color-mix(in srgb, var(--bad) 13%, transparent)', text: 'var(--bad-fg)' },
] as const

export function StatusBandChart({ data, height = 380 }: { data: Array<{ date: string; form: number | null }>; height?: number }) {
  const values = data.map((d) => d.form).filter((v): v is number => v != null)
  const top = Math.max(35, Math.ceil(Math.max(...values, 0) + 5))
  const bottom = Math.min(-45, Math.floor(Math.min(...values, 0) - 5))
  const ticks = monthTicks(data.map((d) => d.date))
  const Tip = chartTip((items, label) => {
    const v = num(items[0]?.value)
    if (!Number.isFinite(v)) return null
    const band = BANDS.find((b) => v >= b.from && v < b.to)
    return { title: tickDate(label), lines: [{ text: `Form ${v > 0 ? '+' : ''}${v.toFixed(1)}${band ? ` · ${band.label}` : ''}`, color: 'var(--run)' }] }
  })
  return (
    <div className="chart chart-bands" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
          {BANDS.map((band) => (
            <ReferenceArea
              key={band.key}
              y1={Math.max(band.from, bottom)}
              y2={Math.min(band.to, top)}
              fill={band.fill}
              fillOpacity={1}
              stroke="none"
              ifOverflow="hidden"
              label={{ value: band.label, position: 'insideLeft', fill: band.text, fontSize: 12, fontWeight: 600 }}
            />
          ))}
          <CartesianGrid vertical={false} horizontal={false} />
          <XAxis dataKey="date" ticks={ticks} tickFormatter={tickDate} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis
            orientation="right"
            domain={[bottom, top]}
            ticks={[20, 5, -10, -30]}
            tickFormatter={(v: number) => (v > 0 ? `+${v}` : String(v))}
            axisLine={false}
            tickLine={false}
            width={36}
            mirror
          />
          <Tooltip content={Tip} cursor={{ stroke: 'var(--faint)', strokeDasharray: '3 3' }} {...TIP} position={{ y: 4 }} />
          <Line
            dataKey="form"
            type="monotone"
            stroke="var(--run)"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 5, stroke: 'var(--card)', strokeWidth: 2 }}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
