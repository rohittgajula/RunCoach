import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../lib/auth'
import { dur } from '../../lib/format'
import { errorText, useApplyToday, useToday } from '../../lib/queries'
import type { TodayCheckin } from '../../lib/types'
import { CheckIcon } from '../Icons'
import { Skeleton } from '../States'
import { WorkoutBar } from '../WorkoutBar'
import { keptPlan, markKept, missingLine, unmarkKept } from './checkinUtil'
import { SignalChips, VerdictPill } from './SignalChips'
import { TodayExplanation } from './TodayExplanation'

/** Morning check-in ("Rest or train?") — pinned above today on the Calendar list. */
export function TodayCard({ compact = false }: { compact?: boolean }) {
  const today = useToday()
  if (today.isPending) return compact ? null : <section className="card today-card"><Skeleton lines={3} /></section>
  // Endpoint not there yet / no athlete data: the calendar works without this card.
  if (today.isError) {
    if (today.error instanceof ApiError && today.error.status === 404) return null
    return compact ? null : <p className="muted small centered-text">{errorText(today.error, 'Morning check-in unavailable.')}</p>
  }
  return compact ? <CompactToday data={today.data} /> : <FullToday data={today.data} />
}

function FullToday({ data }: { data: TodayCheckin }) {
  const apply = useApplyToday()
  const [kept, setKept] = useState(() => keptPlan(data.date))
  const changes = !!data.adjusted && data.verdict !== 'go' && data.verdict !== 'no_plan'
  const decided = data.applied || kept

  return (
    <section className={`card today-card ${decided ? 'is-decided' : ''}`} aria-label="Morning check-in">
      <div className="today-head">
        <VerdictPill verdict={data.verdict} />
        <span className="today-eyebrow">Morning check-in</span>
      </div>
      <h2 className="today-headline">{data.headline}</h2>
      <TodayExplanation today={data} />
      <SignalChips reasons={data.reasons} />
      {data.signals_missing.length > 0 && <p className="today-missing">{missingLine(data.signals_missing)}</p>}
      {data.verdict === 'no_plan' && (
        <p className="today-note">{data.note || 'Nothing planned — an easy 20-min walk keeps you moving.'}</p>
      )}

      {changes && !decided && data.adjusted && (
        <div className="today-suggest">
          <p className="today-suggest-label">
            Instead: <b>{data.adjusted.title}</b> · {dur(data.adjusted.duration_s)}
          </p>
          <WorkoutBar steps={data.adjusted.steps} height={40} compact />
        </div>
      )}

      {changes && data.applied && (
        <p className="today-done"><CheckIcon size={16} /> Adjusted — today’s workout now shows the easier version.</p>
      )}
      {changes && !data.applied && kept && (
        <p className="today-done today-done-muted">
          Keeping the plan.
          <button type="button" className="link-btn" onClick={() => { unmarkKept(data.date); setKept(false) }}>Change</button>
        </p>
      )}
      {changes && !decided && (
        <div className="today-actions">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => { markKept(data.date); setKept(true) }}>
            Keep plan
          </button>
          <button type="button" className="btn btn-primary btn-sm btn-grow" disabled={apply.isPending} onClick={() => apply.mutate()}>
            {apply.isPending ? 'Updating…' : 'Use this'}
          </button>
        </div>
      )}
      {apply.isError && <p className="bad small">{errorText(apply.error, 'Could not adjust today’s workout.')}</p>}
    </section>
  )
}

/** Insights: pill, headline, the why and up to three chips; tap → Calendar. */
function CompactToday({ data }: { data: TodayCheckin }) {
  const navigate = useNavigate()
  const open = () => navigate('/calendar')
  return (
    <section className="card today-card today-compact is-tappable" role="button" tabIndex={0} onClick={open} onKeyDown={(e) => e.key === 'Enter' && open()}>
      <div className="today-head">
        <VerdictPill verdict={data.verdict} />
        <h2 className="today-headline">{data.headline}</h2>
        {data.applied && <span className="tag tag-ok">Adjusted</span>}
      </div>
      <TodayExplanation today={data} />
      <SignalChips reasons={data.reasons} max={3} />
    </section>
  )
}
