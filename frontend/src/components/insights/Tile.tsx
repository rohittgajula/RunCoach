import type { ReactNode } from 'react'
import type { Point } from '../MetricChart'
import { Sparkline } from '../Sparkline'

/** One tappable metric inside an Insights card: label, big value, small line, spark. */
export function Tile({
  label, value, unit, sub, points, onClick, children, color, reversed = false,
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
}) {
  const values = (points ?? []).map((p) => p.value).filter((v): v is number => v != null).map((v) => (reversed ? -v : v))
  return (
    <button type="button" className="tile" onClick={onClick} disabled={!onClick}>
      <span className="tile-label">{label}</span>
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
