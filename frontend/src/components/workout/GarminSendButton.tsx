import { useEffect, useRef, useState } from 'react'
import { timeOfDay } from '../../lib/format'
import { errorText, useRemoveWorkoutFromGarmin, useSendWorkoutToGarmin } from '../../lib/queries'
import type { Workout } from '../../lib/types'
import { CheckIcon, MoreVIcon } from '../Icons'

const syncedAt = (iso: string) => {
  const d = new Date(iso)
  const sameDay = d.toDateString() === new Date().toDateString()
  return sameDay ? timeOfDay(iso) : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/**
 * Send to Garmin → "On your watch ✓ · synced 08:12"; "Update on watch" when the steps
 * changed since; remove from the watch in ⋮. Planned workouts only.
 */
export function GarminSendButton({ workout, compact = false }: { workout: Workout; compact?: boolean }) {
  const send = useSendWorkoutToGarmin()
  const remove = useRemoveWorkoutFromGarmin()
  const [menu, setMenu] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const onWatch = !!workout.garmin_workout_id
  const stale = onWatch && workout.garmin_status === 'changed'
  const busy = send.isPending || remove.isPending

  useEffect(() => {
    if (!menu) return
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setMenu(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [menu])

  const error = send.error ?? remove.error
  return (
    <div className="garmin-send">
      <div className="garmin-send-row" ref={wrap}>
        {onWatch && !stale && compact ? (
          <button
            type="button"
            className="btn btn-primary btn-grow"
            aria-haspopup="menu"
            aria-expanded={menu}
            title={workout.garmin_synced_at ? `Synced ${syncedAt(workout.garmin_synced_at)}` : undefined}
            onClick={() => setMenu(!menu)}
          >
            On watch <CheckIcon size={16} />
          </button>
        ) : onWatch && !stale ? (
          <p className="garmin-on">
            <span className="garmin-check"><CheckIcon size={14} /></span>
            On your watch{workout.garmin_synced_at && <span className="muted"> · synced {syncedAt(workout.garmin_synced_at)}</span>}
          </p>
        ) : (
          <button type="button" className="btn btn-secondary btn-grow" disabled={busy} onClick={() => send.mutate(workout.id)}>
            {send.isPending ? 'Sending…' : stale ? 'Update on watch' : 'Send to Garmin'}
          </button>
        )}
        {onWatch && (
          <div className="menu-wrap">
            {!(compact && !stale) && (
              <button type="button" className="icon-btn" aria-label="Garmin options" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>
                <MoreVIcon />
              </button>
            )}
            {menu && (
              <div className={`menu menu-up ${compact ? 'menu-left' : ''}`} role="menu">
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setMenu(false); send.mutate(workout.id) }}>
                  Send again
                </button>
                <button type="button" role="menuitem" className="bad" disabled={busy} onClick={() => { setMenu(false); remove.mutate(workout.id) }}>
                  {remove.isPending ? 'Removing…' : 'Remove from watch'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
      {stale && <p className="muted small">This workout changed after it was sent.</p>}
      {error && <p className="bad small">{errorText(error, 'Garmin did not accept it. Try again later.')}</p>}
    </div>
  )
}
