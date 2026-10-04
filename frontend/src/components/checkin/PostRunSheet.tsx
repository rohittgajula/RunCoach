import { dur, km, parseDate, timeOfDay } from '../../lib/format'
import type { ActivityCard } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { SportIcon } from '../Cards'
import { CheckinForm } from './CheckinForm'

const when = (iso: string) =>
  `${parseDate(iso.slice(0, 10)).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })} · ${timeOfDay(iso)}`

/** The post-run check-in as its own sheet (auto-prompt and the Calendar card). */
export function PostRunSheet({
  activity, onClose, onFinished,
}: { activity: ActivityCard | null; onClose: () => void; onFinished: (how: 'done' | 'skipped') => void }) {
  return (
    <BottomSheet open={!!activity} onClose={onClose} title="How did it feel?" label="Post-run check-in">
      {activity && (
        <>
          <div className="ci-activity">
            <span className="attach-icon"><SportIcon sport={activity.sport} /></span>
            <div className="grow">
              <p className="ci-activity-name">{activity.name || activity.sport}</p>
              <p className="muted small">
                {when(activity.start)} · {dur(activity.duration_s)}
                {activity.distance_m ? ` · ${km(activity.distance_m)}` : ''}
              </p>
            </div>
          </div>
          <CheckinForm
            key={activity.id}
            activityId={activity.id}
            onDone={() => onFinished('done')}
            onSkipped={() => onFinished('skipped')}
          />
        </>
      )}
    </BottomSheet>
  )
}
