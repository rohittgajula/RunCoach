import { useNavigate } from 'react-router-dom'
import { startPendingChat } from '../lib/pending'
import { startGuide, startReview } from '../lib/queries'
import type { ActivityCard, Workout } from '../lib/types'

export const GUIDE_TEXT = 'How do I execute this workout?'
export const REVIEW_TEXT = 'Review this activity'

/**
 * Guide / Review: fire the (slow) POST, switch to Chat immediately, and let Chat show
 * the attachment + question + "Thinking…" until the thread id arrives.
 */
export function useCoachLaunch() {
  const navigate = useNavigate()
  return {
    guide(workout: Workout) {
      const id = startPendingChat(GUIDE_TEXT, { type: 'workout', workout }, () => startGuide(workout.id))
      navigate(`/chat/new?pending=${id}`)
    },
    review(activity: ActivityCard) {
      if (activity.reviewed_thread_id) {
        navigate(`/chat/${activity.reviewed_thread_id}`)
        return
      }
      const id = startPendingChat(REVIEW_TEXT, { type: 'activity', activity }, () => startReview(activity.id))
      navigate(`/chat/new?pending=${id}`)
    },
  }
}
