import type { ReactNode } from 'react'
import { DeltaChip } from '../ChartFrame'
import { trendOf, type Better } from '../chartUtil'
import type { Point } from '../MetricChart'
import { Sparkline } from '../Sparkline'

/** One tappable metric inside an Insights card: label, big value, small line, spark. */
export function Tile({
  label, value, unit, sub, points, onClick, children, color, reversed = false, better, delta,
}: {
  label: string
  value: string
  unit?: string
  sub?: ReactNode
  points?: Point[]
  onClick?: () => void
  children?: ReactNode
  color?: string
  /** Paces: lower is better, so draw it upside down like the full chart. */
  reversed?: boolean
  /** With `points`: a small ▲/▼ chip, coloured by which direction is good. */
  better?: Better
  delta?: (v: number) => string
}) {
  const trend = points && better !== undefined ? trendOf(points.map((p) => p.value), better) : null
  const values = (points ?? []).map((p) => p.value).filter((v): v is number => v != null).map((v) => (reversed ? -v : v))
  return (
    <button type="button" className="tile" onClick={onClick} disabled={!onClick}>
      <span className="tile-head">
        <span className="tile-label">{label}</span>
        {trend && delta && <DeltaChip trend={trend} format={delta} />}
      </span>
      <span className="tile-value">
        {value}
        {unit && <small> {unit}</small>}
      </span>
      {sub && <span className="tile-sub">{sub}</span>}
      {children}
      {points && <Sparkline values={values} height={32} color={color} />}
    </button>
  )
}

/** Card wrapper with an optional "tap for chart" header action. */
export function InsightCard({
  title, aside, children, className = '',
}: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card insight ${className}`}>
      <div className="card-head">
        <h2 className="card-title">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}
