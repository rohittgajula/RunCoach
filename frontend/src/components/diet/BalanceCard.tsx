import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { addDays, parseDate, todayISO } from '../../lib/format'
import { errorText, useDietTrend } from '../../lib/queries'
import type { DietTrend, Range } from '../../lib/types'
import { TIP, chartTip, num } from '../ChartTip'
import { monthTicks, tickDate } from '../chartUtil'
import { RangeSwitch } from '../RangeSwitch'
import { ErrorState, Skeleton } from '../States'

const NEED_DAYS = 5
const UNDER = 'var(--run-soft)'
const OVER = 'var(--fuel)'
const WEIGHT = 'var(--fg)'
const AXIS_W = 44
const MARGIN = { top: 10, right: 8, left: 0, bottom: 6 }

/**
 * "Nice" axis ticks: steps of 1 / 2 / 2.5 / 5 × 10ⁿ (never below `minStep`), so labels
 * never repeat (weight 75.0 · 75.5 · 76.0, not 75 · 75 · 76).
 */
export function niceTicks(lo: number, hi: number, count = 4, minStep = 0.1): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return []
  if (hi - lo < minStep) { lo -= minStep; hi += minStep }
  const raw = (hi - lo) / Math.max(1, count - 1)
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = Math.max(minStep, [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag)
  const start = Math.floor(lo / step) * step
  const out: number[] = []
  for (let v = start; v <= hi + step * 0.999; v += step) out.push(Math.round(v * 1000) / 1000)
  return out
}

const signedKcal = (v: number) => (v > 0 ? `+${Math.round(v)}` : v < 0 ? `−${Math.abs(Math.round(v))}` : '0')
const round50 = (v: number) => Math.max(50, Math.round(Math.abs(v) / 50) * 50)

type Row = { date: string; balance: number | null; weight: number | null; trend: number | null }

function rows(data: DietTrend): Row[] {
  const series = data.series ?? []
  return series.map((p, i) => {
    // 7-day trend = mean of the weigh-ins in the trailing 7 days.
    const window = series.slice(Math.max(0, i - 6), i + 1).map((x) => x.weight_kg).filter((w): w is number => w != null)
    return {
      date: p.date,
      balance: p.intake_kcal != null ? Math.round(p.intake_kcal - p.target_kcal) : null,
      weight: p.weight_kg,
      trend: window.length ? Math.round((window.reduce((a, b) => a + b, 0) / window.length) * 10) / 10 : null,
    }
  })
}

/** "Last 4 weeks: ~350 kcal/day below your target → weight 76.4 → 75.2 kg (−1.2)". */
function summaryText(all: Row[]): string | null {
  const last = all.slice(-28)
  const bal = last.map((r) => r.balance).filter((v): v is number => v != null)
  if (!bal.length) return null
  const avg = bal.reduce((a, b) => a + b, 0) / bal.length
  const kcal = Math.abs(avg) < 25 ? 'about even with your target' : `~${round50(avg)} kcal/day ${avg < 0 ? 'below' : 'above'} your target`
  const trend = last.map((r) => r.trend).filter((v): v is number => v != null)
  let weight = ''
  if (trend.length >= 2) {
    const a = trend[0]
    const b = trend[trend.length - 1]
    const d = b - a
    weight = ` → weight ${a.toFixed(1)} → ${b.toFixed(1)} kg (${d > 0 ? '+' : d < 0 ? '−' : '±'}${Math.abs(d).toFixed(1)})`
  }
  return `Last 4 weeks: ${kcal}${weight}.`
}

/** Last 7 days as dots: filled = a day with meals logged. */
function LoggedDots({ data }: { data: DietTrend }) {
  const today = todayISO()
  const logged = new Set((data.series ?? []).filter((p) => p.intake_kcal != null).map((p) => p.date))
  const days = Array.from({ length: 7 }, (_, i) => addDays(today, i - 6))
  return (
    <div className="log-dots" role="img" aria-label={`${days.filter((d) => logged.has(d)).length} of the last 7 days logged`}>
      {days.map((d) => (
        <span key={d} className={logged.has(d) ? 'is-on' : ''}>
          <i />
          <small>{parseDate(d).toLocaleDateString('en-GB', { weekday: 'narrow' })}</small>
        </span>
      ))}
    </div>
  )
}

const BalanceTip = chartTip((items, label) => {
  const v = num(items[0]?.value)
  if (!Number.isFinite(v)) return null
  return { title: tickDate(label), lines: [{ text: `${signedKcal(v)} kcal vs target`, color: v < 0 ? UNDER : OVER }] }
})
const WeightTip = chartTip((items, label) => ({
  title: tickDate(label),
  lines: items.flatMap((i) => {
    const v = num(i.value)
    if (!Number.isFinite(v)) return []
    return [{ text: i.dataKey === 'trend' ? `${v.toFixed(1)} kg 7-day trend` : `${v.toFixed(1)} kg weigh-in`, color: WEIGHT }]
  }),
}))

/**
 * Diet → Balance vs weight (R12 feedback): a progress state until 5 of 7 days are logged,
 * then two stacked charts on one time axis — daily balance bars and weight with its
 * 7-day trend — under one plain sentence.
 */
export function BalanceCard() {
  const [range, setRange] = useState<Range>('3m')
  const trend = useDietTrend(range)
  const data = trend.data
  const all = useMemo(() => (data ? rows(data) : []), [data])
  const logged = data?.summary?.logged_days_last_7 ?? 0
  const enough = !!data && logged >= NEED_DAYS

  return (
    <section className="card balance-card">
      <div className="card-head chart-card-head">
        <h2 className="card-title">Balance vs weight</h2>
      </div>
      {trend.isPending && <Skeleton height={200} />}
      {trend.isError && !data && <ErrorState message={errorText(trend.error)} onRetry={() => trend.refetch()} />}
      {data && !enough && (
        <div className="balance-empty">
          <p className="balance-empty-title">Log meals on {NEED_DAYS} of the last 7 days to see this · <b>{logged}/7</b> so far</p>
          <LoggedDots data={data} />
          <p className="muted small">Then this card shows whether you’re eating below or above your daily target, and how your weight follows over the weeks.</p>
        </div>
      )}
      {data && enough && <BalanceCharts all={all} range={range} setRange={setRange} data={data} />}
    </section>
  )
}

function BalanceCharts({ all, range, setRange, data }: { all: Row[]; range: Range; setRange: (r: Range) => void; data: DietTrend }) {
  const ticks = monthTicks(all.map((r) => r.date))
  const bal = all.map((r) => r.balance).filter((v): v is number => v != null)
  const bTicks = niceTicks(Math.min(0, ...bal), Math.max(0, ...bal), 4, 50)
  const weights = all.flatMap((r) => [r.weight, r.trend]).filter((v): v is number => v != null)
  const wTicks = weights.length ? niceTicks(Math.min(...weights), Math.max(...weights), 4, 0.1) : []
  const sentence = summaryText(all)
  const s = data.summary
  return (
    <>
      {sentence && <p className="balance-summary">{sentence}</p>}
      <RangeSwitch value={range} onChange={setRange} />

      <p className="balance-chart-title">Daily balance <span className="muted small">· kcal eaten − daily target</span></p>
      <div className="chart" style={{ height: 150 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={all} margin={MARGIN} syncId="diet-balance">
            <CartesianGrid vertical={false} strokeDasharray="3 4" />
            <XAxis dataKey="date" hide />
            <YAxis width={AXIS_W} ticks={bTicks} domain={[bTicks[0], bTicks[bTicks.length - 1]]} tickFormatter={(v: number) => (v === 0 ? 'even' : signedKcal(v))} axisLine={false} tickLine={false} interval={0} />
            <ReferenceLine y={0} stroke="var(--muted)" strokeOpacity={0.8} />
            <Tooltip content={BalanceTip} cursor={false} {...TIP} />
            <Bar dataKey="balance" isAnimationActive={false} radius={[3, 3, 3, 3]} maxBarSize={10}>
              {all.map((r) => <Cell key={r.date} fill={(r.balance ?? 0) < 0 ? UNDER : OVER} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {wTicks.length > 0 && (
        <>
          <p className="balance-chart-title">Weight <span className="muted small">· kg</span></p>
          <div className="chart" style={{ height: 140 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={all} margin={MARGIN} syncId="diet-balance">
                <CartesianGrid vertical={false} strokeDasharray="3 4" />
                <XAxis dataKey="date" ticks={ticks} tickFormatter={tickDate} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={24} />
                <YAxis width={AXIS_W} ticks={wTicks} domain={[wTicks[0], wTicks[wTicks.length - 1]]} tickFormatter={(v: number) => v.toFixed(1)} axisLine={false} tickLine={false} interval={0} />
                <Tooltip content={WeightTip} cursor={{ stroke: 'var(--faint)', strokeDasharray: '3 3' }} {...TIP} />
                <Line dataKey="weight" stroke="none" dot={{ r: 2.5, fill: 'var(--muted)', strokeWidth: 0 }} activeDot={false} isAnimationActive={false} connectNulls={false} />
                <Line dataKey="trend" stroke={WEIGHT} strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      <div className="legend-chips">
        <span><i style={{ background: UNDER }} />Below target</span>
        <span><i style={{ background: OVER }} />Above target</span>
        {wTicks.length > 0 && <span><i className="dot" />Weigh-in</span>}
        {wTicks.length > 0 && <span><i className="line" />7-day weight trend</span>}
      </div>
      <p className="chart-caption">
        Below 0 = you ate less than your daily target (your target already includes your weight goal). Weight follows the trend over weeks, not days.
        {s?.predicted_kg_per_week != null && s.actual_kg_per_week != null && (
          <span className="block">Expected from the last week’s eating: {s.predicted_kg_per_week > 0 ? '+' : ''}{s.predicted_kg_per_week.toFixed(2)} kg/week · actual trend {s.actual_kg_per_week > 0 ? '+' : ''}{s.actual_kg_per_week.toFixed(2)} kg/week.</span>
        )}
      </p>
    </>
  )
}
