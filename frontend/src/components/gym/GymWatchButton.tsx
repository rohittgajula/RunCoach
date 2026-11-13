/**
 * Send a gym session to the watch.
 *
 * The whole path for this already existed — the endpoint, the Celery push, the
 * mutation hook — and nothing ever called it, so the one thing you could do
 * with a run and not a gym session was start it from your wrist.
 *
 * What lands on the watch is the six lifts, as a Garmin strength workout with
 * a step per movement carrying its sets and reps. The warm-up deliberately
 * does not go: six mobility drills as workout steps means six screens to press
 * through before the part that counts, and a warm-up is the one block nobody
 * needs timing.
 */

import { useState } from 'react'
import { errorText } from '../../lib/queries'
import { useStrengthToWatch } from '../../lib/r13'
import { CheckIcon } from '../Icons'

/** Only what the button needs, so it works from either the Gym page's session
 *  shape or the calendar's `Strength` without the two having to converge. */
type Session = {
  id: number
  date: string
  status: string
  garmin_status: 'none' | 'synced' | 'changed'
  garmin_workout_id: number | null
}

export function GymWatchButton({
  session, canSend, today,
}: { session: Session; canSend: boolean; today: string }) {
  const watch = useStrengthToWatch()
  const [done, setDone] = useState(false)

  const onWatch = !!session.garmin_workout_id
  const stale = onWatch && session.garmin_status === 'changed'
  // Matches what the endpoint will accept, so the button never offers
  // something the server is about to refuse.
  const sendable = session.status === 'planned' && session.date >= today

  if (!sendable && !onWatch) return null

  if (!canSend) {
    return (
      <p className="gym-watch-off small muted">
        Connect Garmin to send this session to your watch.
      </p>
    )
  }

  if (onWatch && !stale) {
    return (
      <div className="gym-watch">
        <p className="garmin-on">
          <span className="garmin-check"><CheckIcon size={14} /></span>
          On your watch
        </p>
        <button
          type="button"
          className="btn btn-plain btn-small"
          disabled={watch.isPending}
          onClick={() => watch.mutate({ id: session.id, remove: true })}
        >
          Remove
        </button>
      </div>
    )
  }

  return (
    <div className="gym-watch">
      <button
        type="button"
        className="btn btn-secondary btn-grow"
        disabled={watch.isPending}
        onClick={() => {
          setDone(false)
          watch.mutate({ id: session.id }, { onSuccess: () => setDone(true) })
        }}
      >
        {watch.isPending ? 'Sending…' : stale ? 'Update on watch' : 'Send to watch'}
      </button>
      {done && !watch.isPending && (
        <p className="small muted" role="status">
          Queued. It appears on the watch at its next sync.
        </p>
      )}
      {watch.error && (
        <p className="small bad" role="alert">
          {errorText(watch.error, 'That did not reach the watch.')}
        </p>
      )}
    </div>
  )
}
