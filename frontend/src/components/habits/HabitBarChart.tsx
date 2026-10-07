import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { TIP, chartTip, num } from '../ChartTip'
import { monthTicks, tickDate } from '../chartUtil'

/** Small count chart (per day or per week): soft bars, the hovered one in full colour. */
export function HabitBarChart({
  data, color, unit, height = 150,
}: { data: Array<{ date: string; value: number }>; color: string; unit: string; height?: number }) {
  const ticks = monthTicks(data.map((d) => d.date))
  const avg = data.length >= 3 ? data.reduce((a, d) => a + d.value, 0) / data.length : null
  const Tip = chartTip((items, label) => {
    const v = num(items[0]?.value)
    const n = Number.isInteger(v) ? String(v) : v.toFixed(1)
    return { title: tickDate(label), lines: [{ text: `${n} ${unit}`, color }] }
  })
  return (
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 40, right: 0, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 4" />
          <XAxis dataKey="date" ticks={ticks} tickFormatter={tickDate} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={24} />
          <YAxis orientation="right" allowDecimals={false} axisLine={false} tickLine={false} width={28} tickCount={3} mirror />
          {avg != null && avg > 0 && (
            <ReferenceLine y={avg} stroke="var(--muted)" strokeDasharray="4 4" strokeOpacity={0.7} label={{ value: `avg ${avg.toFixed(1)}`, position: 'insideTopLeft', fill: 'var(--muted)', fontSize: 11 }} />
          )}
          <Tooltip content={Tip} cursor={false} {...TIP} />
          <Bar
            dataKey="value"
            fill={color}
            fillOpacity={0.55}
            activeBar={{ fill: color, fillOpacity: 1 }}
            radius={[4, 4, 0, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
