import type { Intensity, Step } from '../lib/types'
import { dur, paceBand } from '../lib/format'

const HEIGHT: Record<Intensity, number> = { walk: 0.38, easy: 0.62, moderate: 0.8, hard: 1 }

/** Strides are short but the whole point of the session — keep them visible. */
const MIN_SHARE = 0.012

/**
 * A strip of blocks: width ∝ duration, height ∝ intensity, colour by intensity.
 * `steps === null` (an activity Garmin gave us no structure for) draws a single grey
 * placeholder bar — same footprint, so cards line up.
 */
export function WorkoutBar({
  steps, height = 56, compact = false,
}: { steps: Step[] | null | undefined; height?: number; compact?: boolean }) {
  const usable = (steps ?? []).filter((s) => s.duration_s > 0)
  if (!usable.length) {
    return (
      <div className="wbar" style={{ height }} aria-label="No workout structure">
        <div className="wbar-block wbar-none" style={{ flexGrow: 1, height: '62%' }} />
      </div>
    )
  }
  const total = usable.reduce((sum, s) => sum + s.duration_s, 0)
  return (
    <div
      className={`wbar ${compact ? 'wbar-compact' : ''}`}
      style={{ height }}
      role="img"
      aria-label={`Workout structure: ${usable.map((s) => `${s.label || s.kind} ${dur(s.duration_s)}`).join(', ')}`}
    >
      {usable.map((step, index) => {
        const share = Math.max(step.duration_s / total, MIN_SHARE)
        return (
          <div
            key={index}
            className={`wbar-block wbar-${step.intensity}`}
            style={{ flexGrow: share, flexBasis: 0, height: `${HEIGHT[step.intensity] * 100}%` }}
            title={`${step.label || step.kind} · ${dur(step.duration_s)} ${paceBand(step.pace_min_s, step.pace_max_s)}`}
          />
        )
      })}
    </div>
  )
}
