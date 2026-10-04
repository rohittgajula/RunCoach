import { parseDate } from '../../lib/format'
import type { ActivityCard, CalDay, Workout } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { ActivityCardView, WorkoutCard } from '../Cards'

/** A month-grid day with more than one item: the same cards as the list, then detail. */
export function DaySheet({
  day, onClose, onWorkout, onActivity, onGuide, onReview,
}: {
  day: CalDay | null
  onClose: () => void
  onWorkout: (w: Workout) => void
  onActivity: (a: ActivityCard) => void
  onGuide: (w: Workout) => void
  onReview: (a: ActivityCard) => void
}) {
  const title = day
    ? parseDate(day.date).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
    : ''
  return (
    <BottomSheet open={!!day} onClose={onClose} title={title} label="Day">
      {day && (
        <div className="cal-items">
          {day.items.map((item) =>
            item.type === 'workout' ? (
              <WorkoutCard
                key={`w${item.workout.id}`}
                workout={item.workout}
                onOpen={() => { onClose(); onWorkout(item.workout) }}
                onGuide={() => { onClose(); onGuide(item.workout) }}
              />
            ) : (
              <ActivityCardView
                key={`a${item.activity.id}`}
                activity={item.activity}
                onOpen={() => { onClose(); onActivity(item.activity) }}
                onReview={() => { onClose(); onReview(item.activity) }}
              />
            ),
          )}
        </div>
      )}
    </BottomSheet>
  )
}
