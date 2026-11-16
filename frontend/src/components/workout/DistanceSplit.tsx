/**
 * How far a session goes, split into the running and the walking.
 *
 * A run/walk prescription is given in time — "27 min: 5 min walk, then 4 × (4
 * min run · 2 min walk)" — and the athlete cannot convert that to distance in
 * their head, because the two halves happen at paces about a hundred seconds
 * per kilometre apart. One combined kilometre figure does not fix it either:
 * it hides which part of the session is the training, which for a beginner
 * building continuous running is the part that matters.
 *
 * So both, plus the total, plus the paces the arithmetic used — a figure whose
 * basis is invisible is one the athlete has to take on trust, and these come
 * from their own segmented runs rather than from a constant.
 *
 * Everything here is an average and is labelled as one. It is not a target:
 * covering less on the day is not a failure, and the session is still the
 * prescribed minutes whatever the ground gives.
 */

import { partKm } from '../../lib/format'
import type { Workout } from '../../lib/types'

type Estimate = NonNullable<Workout['distance_estimate']>

/** "10:04" from 604 s/km. */
const paceText = (s: number): string => `${Math.floor(s / 60)}:${String(Math.round(s) % 60).padStart(2, '0')}`

export function DistanceSplit({ estimate }: { estimate: Workout['distance_estimate'] }) {
  if (!estimate || !(estimate.km > 0)) return null
  const e: Estimate = estimate
  // A session can be all running or all walking. Showing a split with a zero
  // in it is noise — the total above already said everything.
  const hasBoth = e.run_km > 0 && e.walk_km > 0
  if (!hasBoth) return null

  return (
    <div className="dsplit">
      <div className="dsplit-rows">
        <div className="dsplit-row">
          <span className="dsplit-swatch wbar-easy" />
          <span className="dsplit-name">Running</span>
          <span className="dsplit-km">≈ {partKm(e.run_km)} km</span>
          <span className="dsplit-pace">{paceText(e.run_pace_s_per_km)}/km</span>
        </div>
        <div className="dsplit-row">
          <span className="dsplit-swatch wbar-walk" />
          <span className="dsplit-name">Walking</span>
          <span className="dsplit-km">≈ {partKm(e.walk_km)} km</span>
          <span className="dsplit-pace">{paceText(e.walk_pace_s_per_km)}/km</span>
        </div>
        <div className="dsplit-row is-total">
          <span className="dsplit-swatch" />
          <span className="dsplit-name">Together</span>
          <span className="dsplit-km">≈ {partKm(e.km)} km</span>
          <span className="dsplit-pace">
            {e.loops ? `≈ ${e.loops} ${e.loops === 1 ? 'loop' : 'loops'}` : ''}
          </span>
        </div>
      </div>
      <p className="dsplit-note">
        Averages at your own paces, from your segmented runs. An estimate, not a
        target — the session is the minutes.
      </p>
    </div>
  )
}
