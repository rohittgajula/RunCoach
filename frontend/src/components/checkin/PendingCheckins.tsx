import { useEffect, useState } from 'react'
import { dur, parseDate } from '../../lib/format'
import { usePendingCheckins } from '../../lib/queries'
import type { ActivityCard } from '../../lib/types'
import { SportIcon } from '../Cards'
import { ChevronRight } from '../Icons'
import { markPrompted, wasPrompted } from './checkinUtil'
import { PostRunSheet } from './PostRunSheet'

const shortDay = (iso: string) =>
  parseDate(iso.slice(0, 10)).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

/**
 * Pending post-run check-ins: a card on the Calendar until done, and the sheet that
 * opens by itself once per activity after load / sync. Closing with X or Skip stops the
 * chain until a sync brings a newer run; Done moves on to the next unprompted one.
 */
export function PendingCheckins() {
  const pending = usePendingCheckins()
  const [open, setOpen] = useState<ActivityCard | null>(null)
  // Ids waiting when the athlete closed the sheet; only newer runs (a later sync) prompt again.
  const [paused, setPaused] = useState<Set<number> | null>(null)
  const items = pending.data ?? []
  const pause = () => setPaused(new Set(items.map((p) => p.activity.id)))

  useEffect(() => {
    if (open || !pending.data) return
    const next = pending.data.find((p) => !wasPrompted(p.activity.id) && !paused?.has(p.activity.id))
    if (!next) return
    markPrompted(next.activity.id)
    setOpen(next.activity)
  }, [pending.data, open, paused])

  if (!items.length && !open) return null
  return (
    <>
      {items.length > 0 && (
        <section className="card pending-card" aria-label="Check-ins to do">
          <p className="pending-title">How did it feel?</p>
          <p className="muted small">
            {items.length === 1 ? 'One run is waiting for a 10-second check-in.' : `${items.length} runs are waiting for a 10-second check-in.`}
          </p>
          <ul className="pending-list">
            {items.slice(0, 3).map(({ activity }) => (
              <li key={activity.id}>
                <button type="button" className="pending-item" onClick={() => setOpen(activity)}>
                  <SportIcon sport={activity.sport} size={18} />
                  <span className="grow">{activity.name || activity.sport}</span>
                  <span className="muted small">{shortDay(activity.start)} · {dur(activity.duration_s)}</span>
                  <ChevronRight size={18} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      <PostRunSheet
        activity={open}
        onClose={() => { pause(); setOpen(null) }}
        onFinished={(how) => { if (how === 'skipped') pause(); setOpen(null) }}
      />
    </>
  )
}
