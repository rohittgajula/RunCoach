import { StatusPill } from '../Kit'
import type { ReactNode } from 'react'
import type { HabitReportHabit } from '../../lib/types'
import { Bullets } from '../Bullets'
import { ChartFrame, DeltaChip } from '../ChartFrame'
import type { Trend } from '../chartUtil'
import { HabitBarChart } from './HabitBarChart'
import { type HabitMeta } from './habitUtil'

const n1 = (v: number | null | undefined) => (v == null ? '--' : v.toFixed(v >= 10 ? 0 : 1))

/** "Now 2.1/day · before 3.4/day" (alcohol per week). */
function amountText(meta: HabitMeta, entry: HabitReportHabit | undefined): string | null {
  const a = entry?.amount
  if (!a || (a.now_per_day == null && a.before_per_day == null)) return null
  const weekly = meta.kind === 'alcohol'
  const scale = (v: number | null) => (v == null ? null : weekly ? v * 7 : v)
  const per = weekly ? '/week' : '/day'
  const now = weekly && a.now_per_week !== undefined ? a.now_per_week : scale(a.now_per_day)
  const before = weekly && a.before_per_week !== undefined ? a.before_per_week : scale(a.before_per_day)
  const pct = a.change_pct != null && Number.isFinite(a.change_pct) ? ` · ${a.change_pct > 0 ? '+' : a.change_pct < 0 ? '−' : ''}${Math.abs(Math.round(a.change_pct))}%` : ''
  return `Now ${n1(now)}${per} · before ${n1(before)}${per}${pct}`
}

/** One habit: status pill, headline, amount chart and the report's findings as bullets. */
export function HabitCard({
  meta, entry, points, chartTitle, sub, color, children, title, aside, className = '',
}: {
  meta: HabitMeta
  entry?: HabitReportHabit
  points: Array<{ date: string; value: number }>
  chartTitle: string
  sub?: string
  color: string
  children?: ReactNode
  title?: string
  aside?: ReactNode
  className?: string
}) {
  const amount = amountText(meta, entry)
  const pct = entry?.amount?.change_pct
  // Less is better for every habit; within ±10 % counts as steady (the report's rule).
  const chip: Trend | null = pct != null && Number.isFinite(pct)
    ? { avg: 0, last: 0, delta: pct, tone: Math.abs(pct) < 10 ? 'flat' : pct < 0 ? 'good' : 'bad' }
    : null
  const hasPoints = points.some((p) => p.value > 0)
  const findings = entry?.findings ?? []
  return (
    <section className={`card insight habit-card ${className}`}>
      <div className="card-head">
        <h2 className="card-title habit-card-title">
          <span aria-hidden="true">{meta.emoji}</span> {title ?? meta.label}
        </h2>
        <div className="habit-card-aside">
          {entry?.status && <StatusPill status={entry.status} />}
          {aside}
        </div>
      </div>
      {entry?.headline && <p className="report-headline">{entry.headline}</p>}
      {children}
      {hasPoints ? (
        <ChartFrame
          title={<>{chartTitle}{sub && <span className="muted small"> · {sub}</span>}</>}
          chip={<DeltaChip trend={chip} format={(v) => `${Math.round(v)}%`} label="vs the previous range" />}
          caption={amount ? `${amount}. Dashed line: your average.` : 'Dashed line: your average for this range.'}
        >
          <HabitBarChart data={points} color={color} unit={meta.units} />
        </ChartFrame>
      ) : (
        <>
          {amount && <p className="muted small">{amount}</p>}
          <p className="muted small">Nothing logged in this range.</p>
        </>
      )}
      {findings.length > 0 && <Bullets items={findings} />}
      {entry?.status === 'not_enough_data' && !findings.length && (
        <p className="muted small">Keep logging for a couple of weeks — then this shows whether it is going up or down and what it does to your sleep, HRV and runs.</p>
      )}
    </section>
  )
}
