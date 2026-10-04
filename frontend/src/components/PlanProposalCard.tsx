import { usePlanDecision, errorText } from '../lib/queries'
import type { PlanSummary } from '../lib/types'
import { PlanTimeline } from './PlanTimeline'

/** Proposed plan inside an assistant message. Nothing is saved until Accept. */
export function PlanProposalCard({ plan }: { plan: PlanSummary }) {
  const decide = usePlanDecision()
  const status = decide.data?.status ?? plan.status
  const busy = decide.isPending ? decide.variables?.decision : null

  return (
    <div className="proposal">
      {status === 'proposed' && <p className="proposal-note">The proposal is not saved until you accept it.</p>}
      <article className="card proposal-card">
        <p className="eyebrow">Plan proposal</p>
        <h3 className="proposal-name">{plan.name}</h3>
        <p className="muted">
          {plan.phase_count} phase{plan.phase_count === 1 ? '' : 's'}
          {plan.race ? ` · ${plan.race.name}` : ''}
        </p>
        {plan.goal && <p className="proposal-goal">{plan.goal}</p>}
        <PlanTimeline phases={plan.phases} />

        {status === 'proposed' ? (
          <div className="proposal-actions">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: plan.id, decision: 'decline' })}
            >
              {busy === 'decline' ? 'Declining…' : 'Decline'}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: plan.id, decision: 'accept' })}
            >
              {busy === 'accept' ? 'Accepting…' : 'Accept'}
            </button>
          </div>
        ) : (
          <p className={`proposal-status proposal-${status}`}>
            {status === 'active' && 'Accepted — your calendar is filled in.'}
            {status === 'declined' && 'Declined.'}
            {status === 'archived' && 'Archived — replaced by a newer plan.'}
          </p>
        )}
        {decide.isError && <p className="bad">{errorText(decide.error, 'Could not update the plan.')}</p>}
      </article>
    </div>
  )
}
