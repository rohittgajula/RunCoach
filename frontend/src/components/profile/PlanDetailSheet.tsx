import { dur, monthDay } from '../../lib/format'
import { errorText, usePlan } from '../../lib/queries'
import { BottomSheet } from '../BottomSheet'
import { PhasePill } from '../PhasePill'
import { PlanTimeline } from '../PlanTimeline'
import { ErrorState, Skeleton } from '../States'

/** All phases with their weeks (planned time + load). */
export function PlanDetailSheet({ planId, onClose }: { planId: number | null; onClose: () => void }) {
  const plan = usePlan(planId)
  const p = plan.data
  const warnings = Array.isArray(p?.summary?.warnings) ? (p?.summary?.warnings as unknown[]).map(String) : []

  return (
    <BottomSheet open={planId != null} onClose={onClose} full label="Plan">
      {plan.isPending && <Skeleton lines={6} />}
      {plan.isError && <ErrorState message={errorText(plan.error)} onRetry={() => plan.refetch()} />}
      {p && (
        <div className="detail">
          <h2 className="detail-title">{p.name}</h2>
          <p className="muted">
            {p.phase_count} phases · {monthDay(p.start)} – {monthDay(p.end)}
            {p.race ? ` · ${p.race.name}` : ''}
          </p>
          {p.goal && <p className="proposal-goal">{p.goal}</p>}
          {warnings.length > 0 && (
            <ul className="warnings">
              {warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}
          <PlanTimeline
            phases={p.phases}
            currentPhaseId={p.current_phase_id}
            extra={(phase) => {
              const weeks = p.weeks.filter((w) => w.phase_id === phase.id)
              return (
                <>
                  <div className="timeline-pill"><PhasePill kind={phase.kind} /></div>
                  {weeks.length > 0 && (
                    <ul className="plan-weeks">
                      {weeks.map((w) => (
                        <li key={w.start}>
                          <span>{monthDay(w.start)} – {monthDay(w.end)}</span>
                          <span className="muted">{dur(w.planned_minutes * 60)} · {Math.round(w.planned_load)} load</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )
            }}
          />
        </div>
      )}
    </BottomSheet>
  )
}
