import type { ReactNode } from 'react'
import { dayMonth, parseDate, todayISO } from '../lib/format'
import type { Phase } from '../lib/types'

const DAY = 86_400_000

export function phaseProgress(phase: Phase, today = todayISO()): string {
  const now = parseDate(today).getTime()
  const start = parseDate(phase.start).getTime()
  const end = parseDate(phase.end).getTime()
  if (now < start) {
    const days = Math.round((start - now) / DAY)
    return days === 1 ? 'Starts tomorrow' : `Starts in ${days} days`
  }
  if (now > end) return 'Completed'
  const weeks = Math.max(1, Math.ceil((end - start + DAY) / (7 * DAY)))
  const week = Math.min(weeks, Math.floor((now - start) / (7 * DAY)) + 1)
  return `Week ${week} of ${weeks}`
}

const range = (start: string, end: string) => `${dayMonth(start)} – ${dayMonth(end)}`

/** The phase the athlete is in, or the next one if the plan has not begun. */
export function focusPhase(phases: Phase[], currentId: number | null): Phase | undefined {
  const sorted = [...phases].sort((a, b) => a.order - b.order)
  if (currentId != null) {
    const current = sorted.find((p) => p.id === currentId)
    if (current) return current
  }
  const today = todayISO()
  return sorted.find((p) => p.end >= today) ?? sorted[sorted.length - 1]
}

/**
 * Circle + line timeline.
 * - `full`: every phase with dates, name and description (proposal card, plan detail).
 * - `compact`: the current phase expanded, the next collapsed, then "N more phases".
 */
export function PlanTimeline({
  phases, currentPhaseId = null, variant = 'full', extra,
}: {
  phases: Phase[]
  currentPhaseId?: number | null
  variant?: 'full' | 'compact'
  extra?: (phase: Phase) => ReactNode
}) {
  const sorted = [...phases].sort((a, b) => a.order - b.order)
  if (!sorted.length) return null

  if (variant === 'full') {
    return (
      <ol className="timeline">
        {sorted.map((phase) => {
          const isCurrent = phase.id === currentPhaseId
          return (
            <li key={phase.id} className={`timeline-item ${isCurrent ? 'is-current' : ''}`}>
              <span className="timeline-dot" />
              <div className="timeline-body">
                <p className="timeline-dates">{range(phase.start, phase.end)}</p>
                <p className="timeline-name">{phase.name}</p>
                {phase.description && <p className="timeline-desc">{phase.description}</p>}
                {isCurrent && <p className="timeline-status">{phaseProgress(phase)}</p>}
                {extra?.(phase)}
              </div>
            </li>
          )
        })}
      </ol>
    )
  }

  const focus = focusPhase(sorted, currentPhaseId) ?? sorted[0]
  const index = sorted.indexOf(focus)
  const next = sorted[index + 1]
  const rest = sorted.slice(index + 2)

  return (
    <ol className="timeline timeline-compact">
      <li className="timeline-item is-current">
        <span className="timeline-dot" />
        <div className="timeline-body">
          <div className="timeline-row">
            <p className="timeline-name">{focus.name}</p>
            <p className="timeline-dates">{range(focus.start, focus.end)}</p>
          </div>
          {focus.description && <p className="timeline-desc clamp-3">{focus.description}</p>}
          <p className="timeline-status">{phaseProgress(focus)}</p>
        </div>
      </li>
      {next && (
        <li className="timeline-item is-muted">
          <span className="timeline-dot" />
          <div className="timeline-body timeline-row">
            <p className="timeline-name">{next.name}</p>
            <p className="timeline-dates">{range(next.start, next.end)}</p>
          </div>
        </li>
      )}
      {rest.length > 0 && (
        <li className="timeline-item is-muted is-more">
          <div className="timeline-body timeline-row">
            <p className="timeline-name">
              {rest.length} more phase{rest.length === 1 ? '' : 's'}
            </p>
            <p className="timeline-dates">{range(rest[0].start, rest[rest.length - 1].end)}</p>
          </div>
        </li>
      )}
    </ol>
  )
}
