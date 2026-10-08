import { Link } from 'react-router-dom'
import { useActiveExperiment } from '../../lib/r14'
import type { Experiment } from '../../lib/r14'
import { ChevronRight } from '../Icons'

const running = (e: Experiment) => e.status === 'active' || e.status === 'scheduled'

/**
 * R14 §7 on Today: a slim chip for the running experiment ("No alcohol · day 9/21 ·
 * 8 of 9 days kept") with a progress bar; once one ends, "your result is ready".
 * R17: up to 3 can run at once — with more than one, a single combined chip
 * ("2 experiments · day 3/14 · 5/21") keeps Today uncluttered.
 */
export function ExperimentChip() {
  const q = useActiveExperiment()
  const list = (q.data?.active_list ?? []).filter(running)
  const e = q.data?.experiment
  if (list.length > 1) {
    const text = `${list.length} experiments · ${list.map((x, i) => x.status === 'scheduled' ? 'soon' : `${i ? '' : 'day '}${x.progress?.day ?? 0}/${x.days}`).join(' · ')}`
    const pct = list.reduce((s, x) => s + (x.progress?.pct ?? 0), 0) / list.length
    return (
      <Link to="/health/experiments" className="slim-chip" aria-label={`${list.length} experiments running: ${list.map((x) => x.title).join(', ')}`}>
        <span aria-hidden="true">🧪</span>
        <span className="grow">
          <b className="block">{text}</b>
          <span className="slim-chip-bar" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} /></span>
        </span>
        <ChevronRight size={18} className="muted" />
      </Link>
    )
  }
  const one = list[0] ?? e
  if (!one) return null
  const ended = one.status === 'completed' || one.status === 'stopped'
  const pct = Math.max(0, Math.min(100, one.progress?.pct ?? 0))
  const today = one.adherence?.today
  return (
    <Link to={`/health/experiments?e=${one.id}`} className="slim-chip" aria-label={`Experiment: ${one.chip || one.title}`}>
      <span aria-hidden="true">🧪</span>
      <span className="grow">
        <b className="block">{ended ? `${one.title}: your result is ready` : one.chip || one.title}</b>
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
