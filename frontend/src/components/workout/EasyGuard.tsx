import { pace } from '../../lib/format'
import type { WorkoutGuard } from '../../lib/types'

/** "Keep heart rate under 145 bpm · pace 10:00–10:45 /km · cadence ~160" + why. */
export function EasyGuard({ guard }: { guard: WorkoutGuard }) {
  const parts = [
    guard.hr_max != null && <>Keep heart rate under <b>{Math.round(guard.hr_max)} bpm</b></>,
    (guard.pace_min_s || guard.pace_max_s) && (
      <>pace <b>{guard.pace_min_s && guard.pace_max_s ? `${pace(guard.pace_min_s)}–${pace(guard.pace_max_s)}` : pace(guard.pace_min_s || guard.pace_max_s)} /km</b></>
    ),
    guard.cadence_target != null && <>cadence <b>~{Math.round(guard.cadence_target)}</b></>,
  ].filter(Boolean)
  if (!parts.length) return null
  return (
    <section className="guard" aria-label="Easy-day guard">
      <p className="guard-title">Easy-day guard</p>
      <p className="guard-rule">
        {parts.map((part, i) => (
          <span key={i}>{i > 0 && ' · '}{part}</span>
        ))}
      </p>
      <p className="guard-why">Easy days build the engine; going harder makes tomorrow worse.</p>
    </section>
  )
}
