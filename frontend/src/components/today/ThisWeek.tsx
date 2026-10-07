import { Link } from 'react-router-dom'
import { dur } from '../../lib/format'
import type { CalendarResponse } from '../../lib/types'
import { TopicRing } from '../Kit'

const isRun = (sport: string) => /run/i.test(sport)

/** This week: km + runs done of planned, ring = time done of time planned. */
export function ThisWeek({ week }: { week: CalendarResponse | undefined }) {
  if (!week) return null
  const w = week.weeks[0]
  let planned = 0
  let done = 0
  let metres = 0
  for (const day of week.days) {
    for (const item of day.items) {
      if (item.type === 'workout') {
        planned += 1
        if (item.workout.status === 'completed') done += 1
      } else if (item.type === 'activity' && isRun(item.activity.sport)) {
        metres += item.activity.distance_m || 0
        if (item.activity.unplanned) done += 1
      }
    }
  }
  const plannedS = w?.planned_s ?? 0
  const actualS = w?.actual_s ?? 0
  const share = plannedS > 0 ? Math.min(100, (actualS / plannedS) * 100) : actualS > 0 ? 100 : 0
  return (
    <Link to="/plan" className="card this-week" aria-label="This week — open Plan">
      <div className="grow">
        <span className="lbl">This week</span>
        <p className="this-week-main">
          {(metres / 1000).toFixed(1)} km · {planned ? `${done} of ${planned} runs` : `${done} ${done === 1 ? 'run' : 'runs'}`}
        </p>
        <p className="muted small">{plannedS ? `${dur(actualS)} of ${dur(plannedS)} planned` : actualS ? `${dur(actualS)} · no plan` : 'Nothing logged yet'}</p>
      </div>
      <TopicRing value={share} topic="run" size={60} stroke={14} label="Week done" display="" />
    </Link>
  )
}
