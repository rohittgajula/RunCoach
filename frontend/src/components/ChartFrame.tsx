import type { ReactNode } from 'react'
import type { Trend } from './chartUtil'

/** ▲ / ▼ change vs the previous period; green/red only when the direction has a "better". */
export function DeltaChip({ trend, format, unit = '', label = 'vs previous period' }: { trend: Trend | null; format: (v: number) => string; unit?: string; label?: string }) {
  if (!trend) return null
  const arrow = trend.tone === 'flat' ? '–' : trend.delta > 0 ? '▲' : '▼'
  const word = trend.tone === 'good' ? 'better' : trend.tone === 'bad' ? 'worse' : trend.tone === 'flat' ? 'no change' : 'changed'
  return (
    <span className={`delta-chip is-${trend.tone}`} title={label} aria-label={`${word}, ${format(Math.abs(trend.delta))}${unit ? ` ${unit}` : ''} ${label}`}>
      <span className="delta-arrow" aria-hidden="true">{arrow}</span>
      {trend.tone !== 'flat' && <>{format(Math.abs(trend.delta))}{unit ? <small> {unit}</small> : null}</>}
    </span>
  )
}

/** A chart with its header (title + delta chip) and a one-line "what this means" caption. */
export function ChartFrame({
  title, chip, caption, children, className = '',
}: { title?: ReactNode; chip?: ReactNode; caption?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`chart-frame ${className}`}>
      {(title || chip) && (
        <div className="chart-frame-head">
          {title && <span className="chart-frame-title">{title}</span>}
          {chip}
        </div>
      )}
      {children}
      {caption && <p className="chart-caption">{caption}</p>}
    </div>
  )
}
