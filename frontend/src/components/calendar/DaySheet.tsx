import { StrengthCard } from '../strength/StrengthCard'
import { parseDate } from '../../lib/format'
import type { ActivityCard, CalDay, Workout } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { ActivityCardView, WorkoutCard } from '../Cards'
import { AddSession } from '../day/AddSession'

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
          {/* An empty day is no longer a dead end. It used to be the one
              square on the grid you could see and not open, which made a rest
              day the only day you could not put your own session on. */}
          {!day.items.length && (
            <p className="muted small">Nothing planned for this day.</p>
          )}
          {day.items.map((item) =>
            item.type === 'workout' ? (
              <WorkoutCard
                key={`w${item.workout.id}`}
                workout={item.workout}
                onOpen={() => { onClose(); onWorkout(item.workout) }}
                onGuide={() => { onClose(); onGuide(item.workout) }}
              />
            ) : item.type === 'strength' ? (
              <StrengthCard key={`s${item.strength.id}`} session={item.strength} />
            ) : (
              <ActivityCardView
                key={`a${item.activity.id}`}
                activity={item.activity}
                onOpen={() => { onClose(); onActivity(item.activity) }}
                onReview={() => { onClose(); onReview(item.activity) }}
              />
            ),
          )}
          <AddSession date={day.date} onDone={onClose} />
        </div>
      )}
    </BottomSheet>
  )
}
