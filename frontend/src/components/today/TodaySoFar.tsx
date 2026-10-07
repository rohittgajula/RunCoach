import { Link } from 'react-router-dom'
import { useDaySummary } from '../../lib/queries'
import { n0, stressWord } from '../day/dayUtil'
import { ChevronRight } from '../Icons'
import { TopicRing } from '../Kit'
import { clock } from '../weather/weatherUtil'

/** Today: steps ring, stress now, Body Battery now → Health → Day. Hidden without data. */
export function TodaySoFar() {
  const q = useDaySummary()
  const s = q.data
  if (!s || !s.available || (s.steps == null && s.stress == null && s.body_battery == null)) return null
  const asOf = s.data_as_of ?? s.stress_at ?? s.body_battery_at
  return (
    <Link to="/health/day" className="card so-far-wrap" aria-label="Today so far — open your day">
      <div className="so-far-head">
        <span className="lbl grow">Today so far{asOf ? ` · up to ${clock(asOf)}` : ''}</span>
        <ChevronRight size={18} className="muted" />
      </div>
      <div className="so-far">
        <div>
          <TopicRing value={s.steps ?? 0} max={s.step_goal || Math.max(1, s.steps ?? 1)} topic="run" size={56} stroke={14} label="Steps toward goal" display={s.pct != null ? `${s.pct}%` : ''} />
          <span className="so-lbl">{s.steps != null ? `${n0(s.steps)} steps` : 'Steps —'}</span>
        </div>
        <div>
          <span className="so-num" style={{ color: 'var(--recovery)' }}>{s.stress ?? '—'}</span>
          <span className="so-lbl">Stress{s.stress != null ? ` · ${stressWord(s.stress)}` : ''}</span>
        </div>
        <div>
          <span className="so-num" style={{ color: 'var(--sleep)' }}>{s.body_battery ?? '—'}</span>
          <span className="so-lbl">Body Battery</span>
        </div>
      </div>
    </Link>
  )
}
