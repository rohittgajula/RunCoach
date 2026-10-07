import { Link } from 'react-router-dom'
import { useGoalChip } from '../../lib/r14'
import { ChevronRight, FlagIcon } from '../Icons'

/** R14 §8: one line on Health → Overview — the active goal closest to done. */
export function GoalChip() {
  const q = useGoalChip()
  const g = q.data?.goal
  const text = q.data?.text || g?.chip
  if (!g || !text) return null
  const pct = Math.max(0, Math.min(100, g.progress_pct ?? 0))
  return (
    <Link to="/health/goals" className="slim-chip" aria-label={`Goal: ${text}`}>
      <FlagIcon size={20} />
      <span className="grow">
        <b className="block">{text}</b>
        <span className="slim-chip-bar goal-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}
