import { errorText, useWorkoutReview } from '../../lib/queries'
import type { Workout } from '../../lib/types'
import { ActualVsPlanned } from './ActualVsPlanned'
import { CoachReviewCard } from './CoachReviewCard'
import { ComplianceCard } from './ComplianceCard'

/** R6 §3: everything a completed workout adds to the detail sheet. */
export function WorkoutResult({ workout }: { workout: Workout }) {
  const review = useWorkoutReview(workout.id)
  if (!workout.actual) return null
  return (
    <>
      <ActualVsPlanned planned={workout.steps} plannedDuration={workout.duration_s} actual={workout.actual} />
      {workout.compliance && <ComplianceCard compliance={workout.compliance} />}
      <CoachReviewCard
        review={workout.review}
        onGenerate={() => review.mutate()}
        pending={review.isPending}
        error={review.isError ? errorText(review.error, 'Could not get a review. Try again.') : undefined}
      />
    </>
  )
}
