import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { monthTicks, tickDate } from '../chartUtil'

/** Small count chart (per day or per week) — bars, no fill gradients. */
export function HabitBarChart({
  data, color, unit, height = 140,
}: { data: Array<{ date: string; value: number }>; color: string; unit: string; height?: number }) {
  const ticks = monthTicks(data.map((d) => d.date))
  return (
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 4, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="date" ticks={ticks} tickFormatter={tickDate} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={24} />
          <YAxis orientation="right" allowDecimals={false} axisLine={false} tickLine={false} width={32} tickCount={3} />
          <Tooltip
            formatter={(value) => [`${value} ${unit}`, '']}
            labelFormatter={(label) => tickDate(String(label))}
            separator=""
            cursor={{ fill: 'var(--card-2)' }}
          />
          <Bar dataKey="value" fill={color} radius={[3, 3, 0, 0]} maxBarSize={24} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
