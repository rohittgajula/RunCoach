import type { HabitSummary } from '../../lib/types'
import { HabitBarChart } from './HabitBarChart'

const hasAny = (points: Array<{ value: number }>) => points.some((p) => p.value > 0)
const fmt = (v: number | null | undefined, digits = 1) => (v == null ? '--' : v.toFixed(digits))

/** Cigarettes/day, drinks/week, sugar/day — each only once something was logged. */
export function HabitCharts({ data }: { data: HabitSummary }) {
  const smoke = data.smoke.series.map((p) => ({ date: p.date, value: p.count }))
  const sugar = data.sugar.series.map((p) => ({ date: p.date, value: p.count }))
  // Weekly drinks come from `weekly`; fall back to summing the daily series.
  const drinks = data.weekly.length
    ? data.weekly.map((w) => ({ date: w.week_start, value: w.drinks }))
    : data.alcohol.series.map((p) => ({ date: p.date, value: p.count }))
  const rows = [
    { key: 'smoke', title: 'Cigarettes per day', sub: `avg ${fmt(data.smoke.per_day_avg)}/day`, points: smoke, color: '#8a8d99', unit: 'cigarettes' },
    { key: 'alcohol', title: 'Drinks per week', sub: `avg ${fmt(data.alcohol.per_week_avg)}/week · ${data.alcohol.drink_days} drink ${data.alcohol.drink_days === 1 ? "day" : "days"}`, points: drinks, color: '#d9861a', unit: 'drinks' },
    { key: 'sugar', title: 'Sugar per day', sub: `avg ${fmt(data.sugar.per_day_avg)}/day`, points: sugar, color: '#8d6be8', unit: 'servings' },
  ].filter((r) => hasAny(r.points))

  if (!rows.length) return <p className="muted small">Nothing logged in this range yet. Tap the buttons above when it happens — honest logs make the trends useful.</p>

  return (
    <div className="habit-charts">
      {rows.map((r) => (
        <div key={r.key} className="habit-chart">
          <div className="habit-chart-head">
            <span className="habit-chart-title">{r.title}</span>
            <span className="muted small">{r.sub}</span>
          </div>
          <HabitBarChart data={r.points} color={r.color} unit={r.unit} />
        </div>
      ))}
    </div>
  )
}
