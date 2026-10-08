import { useDecideReview } from '../../lib/r17lazy'
import type { RunDecision } from '../../lib/r17'

export type DayFlagInfo = { reason: 'illness' | string; text: string; illness_id?: number | null; decision: RunDecision } | null | undefined

/**
 * R17: a day inside an illness is flagged, never auto-excluded — a quiet note on
 * Health → Day with the athlete's own choice (reversible).
 */
export function DayFlag({ date, flag }: { date: string; flag: DayFlagInfo }) {
  const decide = useDecideReview()
  if (!flag) return null
  const out = flag.decision === 'exclude'
  const set = (decision: RunDecision) => decide.mutate([{ kind: 'day', date, decision }])
  return (
    <p className="excluded-note" role="note">
      <span aria-hidden="true">🤒</span>
      <span className="grow">{flag.text || 'You were unwell this day.'} {out ? <b>Excluded by you.</b> : 'Still counted in trends.'}</span>
      <button type="button" disabled={decide.isPending} onClick={() => set(out ? 'include' : 'exclude')}>{out ? 'Include' : 'Exclude'}</button>
    </p>
  )
}
