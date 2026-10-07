import { Link } from 'react-router-dom'
import { useActiveExperiment } from '../../lib/r14'
import { ChevronRight } from '../Icons'

/**
 * R14 §7 on Today: a slim chip for the running experiment ("No alcohol · day 9/21 ·
 * 8 of 9 days kept") with a progress bar; once one ends, "your result is ready".
 */
export function ExperimentChip() {
  const q = useActiveExperiment()
  const e = q.data?.experiment
  if (!e) return null
  const ended = e.status === 'completed' || e.status === 'stopped'
  const pct = Math.max(0, Math.min(100, e.progress?.pct ?? 0))
  const today = e.adherence?.today
  return (
    <Link to={`/health/experiments?e=${e.id}`} className="slim-chip" aria-label={`Experiment: ${e.chip || e.title}`}>
      <span aria-hidden="true">🧪</span>
      <span className="grow">
        <b className="block">{ended ? `${e.title}: your result is ready` : e.chip || e.title}</b>
        {!ended && (
          <>
            <span className="slim-chip-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></span>
            {today != null && <span className="muted small block" style={{ marginTop: 4 }}>{today ? 'Kept today so far ✓' : 'Not kept today'}</span>}
          </>
        )}
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}
