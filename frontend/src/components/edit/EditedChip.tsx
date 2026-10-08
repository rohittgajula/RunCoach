import { todayISO } from '../../lib/format'
import type { Workout } from '../../lib/types'

/** R16 §A: "Edited by you" on workouts the athlete changed (app or chat). */
export function EditedChip({ workout, className = '' }: { workout: Pick<Workout, 'edited_by' | 'edited_via'>; className?: string }) {
  if (workout.edited_by !== 'user') return null
  return (
    <span className={`tag tag-edited ${className}`} title={workout.edited_via === 'chat' ? 'Changed in chat with the coach' : 'You changed this workout'}>
      Edited by you
    </span>
  )
}

/** Server flag when present (R16), else the old rule: planned, today or later. */
export const canEditWorkout = (w: Workout) =>
  w.can_edit ?? (w.status === 'planned' && w.date >= todayISO() && !w.completed_activity_id)
