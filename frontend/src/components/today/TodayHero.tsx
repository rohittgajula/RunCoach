import { useBriefing } from '../../lib/r13'
import { useToday } from '../../lib/queries'
import type { CalDay } from '../../lib/types'
import { BriefingDetails } from '../briefing/BriefingCard'
import { CheckinDecision, TodayCard, useReadinessScore } from '../checkin/TodayCard'
import { VerdictPill } from '../checkin/SignalChips'
import { SeeDetails } from '../Disclose'
import { InfoButton } from '../health/InfoButton'
import { TopicRing } from '../Kit'
import { TodayWorkout } from './TodayWorkout'

/**
 * R14 §1 Today hero — one card: readiness ring + headline, the one-line focus, the
 * check-in's suggested change (only while undecided), and today's session. The full
 * check-in reasons, the morning briefing (weather, fuel, notes, AI sentence) and mood
 * "Change" sit behind "See details".
 */
export function TodayHero({ day, loading }: { day: CalDay | undefined; loading: boolean }) {
  const today = useToday()
  const briefing = useBriefing()
  const t = today.data
  const b = briefing.data
  const score = useReadinessScore(t)
  const ringScore = score ?? b?.readiness?.score ?? null
  const headline = t?.headline || b?.checkin?.headline || (b?.readiness?.label ? `Readiness ${b.readiness.label.toLowerCase()}` : '')
  const focus = b?.ready ? b.focus?.text : null

  return (
    <section className="card today-hero" aria-label="Today">
      {(ringScore != null || headline) && (
        <div className="today-hero-top">
          <TopicRing value={ringScore} topic="recovery" size={72} stroke={12} label="Readiness" />
          <div className="grow">
            <div className="today-head">
              <span className="lbl title-info">Readiness<InfoButton k="readiness" /></span>
              {t && <VerdictPill verdict={t.verdict} />}
            </div>
            {headline && <h2 className="today-headline">{headline}</h2>}
          </div>
        </div>
      )}
      {focus && (
        <p className="today-hero-focus"><span aria-hidden="true">🎯</span><span>{focus}</span></p>
      )}
      {t && <CheckinDecision data={t} />}
      <TodayWorkout day={day} loading={loading} embedded />
      {(t || b?.ready) && (
        <div className="today-hero-foot">
          <SeeDetails label="Why, weather & fuel" title="Today in detail">
            <TodayCard details />
            <BriefingDetails />
          </SeeDetails>
        </div>
      )}
    </section>
  )
}
