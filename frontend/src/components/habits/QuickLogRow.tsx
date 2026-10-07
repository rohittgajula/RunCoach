import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useAuth } from '../../lib/AuthContext'
import { ApiError } from '../../lib/auth'
import { errorText, useDeleteHabitLog, useHabitsToday, useLogHabit } from '../../lib/queries'
import type { HabitKind, HabitLog } from '../../lib/types'
import { MoreHIcon } from '../Icons'
import { HabitIcon } from './HabitIcon'
import { HabitLogSheet } from './HabitLogSheet'
import { habitMeta, loggableHabits, loggedText } from './habitUtil'

const LONG_PRESS_MS = 500

type Toast = { text: string; log: HabitLog | null }

/**
 * 🚬 🍺 🍫 — tap logs one now (with Undo); long-press or ⋯ opens the full form.
 * 🌙 only when the private habit is enabled AND set to show on today's card.
 */
export function QuickLogRow({ label = 'Log', aside }: { label?: string; aside?: ReactNode }) {
  const { athlete } = useAuth()
  const habits = loggableHabits(athlete, 'today')
  const today = useHabitsToday()
  const log = useLogHabit()
  const remove = useDeleteHabitLog()
  const [sheet, setSheet] = useState<HabitKind | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longPressed = useRef(false)

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 8000)
    return () => clearTimeout(t)
  }, [toast])

  // Endpoint not deployed yet: the row simply isn't there.
  if (today.isError && today.error instanceof ApiError && today.error.status === 404) return null

  const counts = today.data?.counts

  const tap = (kind: HabitKind) => {
    if (longPressed.current) {
      longPressed.current = false
      return
    }
    setToast({ text: `${habitMeta(kind).emoji} Logging…`, log: null })
    log.mutate(
      { kind, quantity: 1 },
      {
        onSuccess: (saved) => setToast({ text: loggedText(kind, saved?.quantity ?? 1), log: saved ?? null }),
        onError: (error) => setToast({ text: errorText(error, 'Could not log that.'), log: null }),
      },
    )
  }

  const pressStart = (kind: HabitKind) => {
    longPressed.current = false
    timer.current = setTimeout(() => {
      longPressed.current = true
      setSheet(kind)
    }, LONG_PRESS_MS)
  }
  const pressEnd = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }

  const undo = () => {
    const saved = toast?.log
    if (!saved) return
    setToast(null)
    remove.mutate(saved, {
      onSuccess: () => setToast({ text: 'Removed', log: null }),
      onError: (error) => setToast({ text: errorText(error, 'Could not undo.'), log: null }),
    })
  }

  return (
    <div className="quicklog" aria-label="Quick log">
      <div className="quicklog-head">
        <span className="quicklog-label">{label}</span>
        {aside && <span className="quicklog-aside">{aside}</span>}
      </div>
      <div className="quicklog-buttons" style={{ gridTemplateColumns: `repeat(${habits.length}, minmax(0, 1fr)) 44px` }}>
        {habits.map((h) => {
          const n = counts?.[h.kind] ?? 0
          return (
            <button
              key={h.kind}
              type="button"
              className={`quicklog-btn ${n > 0 ? 'has-count' : ''}`}
              aria-label={h.kind === 'private' ? `Log 🌙 Private now (${n} today). Long-press for more options.` : `Log one ${h.unit} now (${n} today). Long-press for more options.`}
              onClick={() => tap(h.kind)}
              onPointerDown={() => pressStart(h.kind)}
              onPointerUp={pressEnd}
              onPointerLeave={pressEnd}
              onPointerCancel={pressEnd}
              onContextMenu={(e) => e.preventDefault()}
            >
              <HabitIcon kind={h.kind} />
              <span className="quicklog-count">{Number.isInteger(n) ? n : n.toFixed(1)}</span>
            </button>
          )
        })}
        <button type="button" className="quicklog-btn quicklog-more" aria-label="Log with quantity, time or note, or fix today’s entries" onClick={() => setSheet('smoke')}>
          <MoreHIcon size={20} />
        </button>
      </div>
      <HabitLogSheet
        kind={sheet}
        kinds={habits}
        onClose={() => setSheet(null)}
        onLogged={(saved) => setToast({ text: loggedText(saved.kind, saved.quantity), log: saved })}
      />
      {toast && (
        <div className="toast toast-action" role="status">
          <span>{toast.text}</span>
          {toast.log && (
            <button type="button" className="toast-btn" onClick={undo}>Undo</button>
          )}
        </div>
      )}
    </div>
  )
}
