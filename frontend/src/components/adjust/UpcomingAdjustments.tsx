import { useAuth } from '../../lib/AuthContext'
import { parseDate, todayISO } from '../../lib/format'
import { useAdjustments } from '../../lib/r13'
import { CardHead } from '../Kit'
import { AdjustedChip } from './AdjustedChip'

/**
 * R13 §1 on Today: changes auto-adjust made to the next sessions (today's own change is
 * on the workout card). Each with its reason and Undo. Hidden when there are none.
 */
export function UpcomingAdjustments() {
  const { athlete } = useAuth()
  const q = useAdjustments(athlete?.auto_adjust_plan !== false)
  const today = todayISO()
  const rows = (q.data?.adjustments ?? []).filter((a) => a.status === 'applied' && a.workout_date > today).slice(0, 3)
  if (!rows.length) return null
  return (
    <section className="card stack-sm" aria-label="Plan adjusted">
      <CardHead title="Plan adjusted" sub="Tuned to how your body is doing. Undo any change you disagree with." />
      {rows.map((a) => (
        <div key={a.id} className="stack-sm">
          <span className="lbl">{parseDate(a.workout_date).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}</span>
          <AdjustedChip adjustment={a} />
        </div>
      ))}
    </section>
  )
}
