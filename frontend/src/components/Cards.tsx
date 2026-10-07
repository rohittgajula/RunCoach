import { dur, km, parseDate } from '../lib/format'
import type { ActivityCard, Workout } from '../lib/types'
import { ActivityIcon, CheckIcon, ReviewIcon, RunIcon, WalkIcon } from './Icons'
import { PhasePill } from './PhasePill'
import { WorkoutBar } from './WorkoutBar'
import { AdjustedChip } from './adjust/AdjustedChip'

export function SportIcon({ sport, size = 20 }: { sport: string; size?: number }) {
  const s = sport.toLowerCase()
  if (s.includes('walk') || s.includes('hik')) return <WalkIcon size={size} />
  if (s.includes('run')) return <RunIcon size={size} />
  return <ActivityIcon size={size} />
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-stat">
      <span className="mini-stat-label">{label}</span>
      <span className="mini-stat-value">{value}</span>
    </div>
  )
}

/** Planned workout card (calendar). */
export function WorkoutCard({
  workout, onOpen, onGuide, adjusted = false,
}: { workout: Workout; onOpen: () => void; onGuide: () => void; adjusted?: boolean }) {
  return (
    <article
      className={`card cal-card is-tappable ${workout.status === 'skipped' ? 'is-skipped' : ''}`}
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onOpen()}
    >
      <header className="cal-card-head">
        <RunIcon size={20} />
        <span className="cal-card-kind">Plan</span>
        {workout.status === 'completed' && (
          <span className="tag tag-ok">
            <CheckIcon size={14} /> Done
          </span>
        )}
        {workout.status === 'skipped' && <span className="tag">Skipped</span>}
        {(adjusted || workout.adjusted_by === 'checkin' || workout.adjusted_by === 'auto') && workout.status === 'planned' && <span className="tag tag-adjusted">Adjusted</span>}
      </header>
      <WorkoutBar steps={workout.steps} />
      <p className="cal-card-title">{workout.title}</p>
      {workout.auto_adjustment && workout.status === 'planned' && <AdjustedChip adjustment={workout.auto_adjustment} compact />}
      <footer className="cal-card-foot">
        {workout.phase && <PhasePill kind={workout.phase.kind} />}
        <Stat label="Duration" value={dur(workout.duration_s)} />
        <Stat label="Load" value={String(Math.round(workout.load))} />
        <button
          type="button"
          className="btn btn-primary btn-pill"
          onClick={(e) => {
            e.stopPropagation()
            onGuide()
          }}
        >
          <ReviewIcon size={18} /> Guide
        </button>
      </footer>
    </article>
  )
}

/** Synced activity card (calendar). */
export function ActivityCardView({
  activity, onOpen, onReview,
}: { activity: ActivityCard; onOpen: () => void; onReview: () => void }) {
  return (
    <article className="card cal-card is-tappable" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen()}>
      <header className="cal-card-head">
        <SportIcon sport={activity.sport} />
        <div>
          <span className="cal-card-kind">{activity.name || activity.sport}</span>
          <p className="cal-card-sub">{activity.device ? `${activity.device} via Garmin` : 'via Garmin'}</p>
        </div>
        {activity.unplanned && <span className="tag tag-extra" title="Not in the plan — still counts">Extra</span>}
      </header>
      <WorkoutBar steps={activity.steps} />
      <footer className="cal-card-foot">
        <Stat label="Duration" value={dur(activity.duration_s)} />
        <Stat label="Distance" value={activity.distance_m ? km(activity.distance_m) : '—'} />
        <Stat label="Load" value={String(Math.round(activity.load))} />
        <button
          type="button"
          className="btn btn-primary btn-pill"
          onClick={(e) => {
            e.stopPropagation()
            onReview()
          }}
        >
          <ReviewIcon size={18} /> {activity.reviewed_thread_id ? 'Open' : 'Review'}
        </button>
      </footer>
    </article>
  )
}

const shortDate = (iso: string) => {
  const d = parseDate(iso)
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getFullYear()).slice(2)}`
}

/** Compact attachment above a user bubble (chat). */
export function WorkoutAttachment({ workout, onOpen }: { workout: Workout; onOpen?: () => void }) {
  return (
    <button type="button" className="attach" onClick={onOpen} disabled={!onOpen}>
      <span className="attach-head">
        <span className="attach-icon">
          <RunIcon size={20} />
        </span>
        <span>
          <span className="attach-title">{workout.title}</span>
          <span className="attach-sub">
            {shortDate(workout.date)} {workout.status === 'planned' ? 'Planned' : workout.status === 'completed' ? 'Completed' : 'Skipped'}
          </span>
        </span>
      </span>
      <WorkoutBar steps={workout.steps} height={44} />
    </button>
  )
}

export function ActivityAttachment({ activity, onOpen }: { activity: ActivityCard; onOpen?: () => void }) {
  return (
    <button type="button" className="attach" onClick={onOpen} disabled={!onOpen}>
      <span className="attach-head">
        <span className="attach-icon">
          <SportIcon sport={activity.sport} />
        </span>
        <span>
          <span className="attach-title">{activity.name || activity.sport}</span>
          <span className="attach-sub">
            {shortDate(activity.start.slice(0, 10))} · {dur(activity.duration_s)}
            {activity.distance_m ? ` · ${km(activity.distance_m)}` : ''}
          </span>
        </span>
      </span>
      <WorkoutBar steps={activity.steps} height={44} />
    </button>
  )
}
