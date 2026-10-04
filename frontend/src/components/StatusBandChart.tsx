import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { monthTicks, tickDate } from './chartUtil'

/**
 * Training status = form (fitness − fatigue) against fixed bands:
 *  Detraining > +20 · Fresh +5…+20 · Maintaining −10…+5 · Gaining Fitness −30…−10 ·
 *  Overtraining Risk < −30. Thresholds are the backend's (SPEC §3).
 */
export const BANDS = [
  { key: 'detraining', label: 'Detraining', from: 20, to: Infinity, fill: 'rgba(245, 166, 35, 0.16)', text: '#d98a0b' },
  { key: 'fresh', label: 'Fresh', from: 5, to: 20, fill: 'rgba(31, 122, 224, 0.13)', text: '#1f7ae0' },
  { key: 'maintaining', label: 'Maintaining', from: -10, to: 5, fill: 'rgba(140, 140, 160, 0.10)', text: 'var(--text)' },
  { key: 'gaining', label: 'Gaining Fitness', from: -30, to: -10, fill: 'rgba(52, 168, 83, 0.15)', text: '#2f9e55' },
  { key: 'overtraining', label: 'Overtraining Risk', from: -Infinity, to: -30, fill: 'rgba(229, 72, 77, 0.14)', text: '#e5484d' },
] as const

export function StatusBandChart({ data, height = 380 }: { data: Array<{ date: string; form: number | null }>; height?: number }) {
  const values = data.map((d) => d.form).filter((v): v is number => v != null)
  const top = Math.max(35, Math.ceil(Math.max(...values, 0) + 5))
  const bottom = Math.min(-45, Math.floor(Math.min(...values, 0) - 5))
  const ticks = monthTicks(data.map((d) => d.date))
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
              label={{ value: band.label, position: 'insideLeft', fill: band.text, fontSize: 13, fontWeight: 600 }}
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
          />
          <Tooltip
            formatter={(value) => [typeof value === 'number' ? value.toFixed(1) : String(value), 'Form']}
            labelFormatter={(label) => tickDate(String(label))}
          />
          <Line
            dataKey="form"
            type="monotone"
            stroke="#2f9e55"
            strokeWidth={2.5}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
