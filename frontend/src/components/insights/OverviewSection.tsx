import { useState } from 'react'
import { errorText, useInsights } from '../../lib/queries'
import type { InsightRange } from '../../lib/types'
import { TodayCard } from '../checkin/TodayCard'
import { FitnessSheet } from '../profile/FitnessSheet'
import { RangeSwitch } from '../RangeSwitch'
import { ErrorState, Skeleton } from '../States'
import { FocusCard, LoadCard, SummaryCard } from './AdviceCards'
import { INSIGHT_RANGES, InsightChartSheet } from './InsightChartSheet'
import type { ChartKey } from './charts'
import { BreathingCard, FitnessCard, RecoveryCard } from './RecoveryCards'
import { ReadinessCard, RunningCard } from './RunningCards'
import { HabitsTeaser, ProgressTeaser } from './Teasers'

/** Insights → Overview: today's cards; Progress and Habits are one-row teasers. */
export function OverviewSection() {
  const [range, setRange] = useState<InsightRange>('4w')
  const [chart, setChart] = useState<ChartKey | null>(null)
  const [fitnessOpen, setFitnessOpen] = useState(false)
  const insights = useInsights(range)
  const data = insights.data

  return (
    <>
      <TodayCard compact />
      <RangeSwitch value={range} onChange={setRange} options={INSIGHT_RANGES} />

      {insights.isPending && [0, 1, 2].map((i) => (
        <section key={i} className="card"><Skeleton lines={4} /></section>
      ))}
      {insights.isError && !data && (
        <ErrorState message={errorText(insights.error, 'Insights did not load.')} onRetry={() => insights.refetch()} />
      )}

      {data && (
        <div className={`stack ${insights.isPlaceholderData ? 'is-stale' : ''}`}>
          <ReadinessCard data={data} />
          <RunningCard data={data} onChart={setChart} />
          <ProgressTeaser />
          <RecoveryCard data={data} onChart={setChart} />
          <BreathingCard data={data} onChart={setChart} />
          <FitnessCard data={data} onChart={setChart} />
          <LoadCard load={data.load} onOpen={() => setFitnessOpen(true)} />
          <FocusCard focus={data.focus ?? []} hasRuns={(data.running?.runs ?? 0) > 0} />
          <HabitsTeaser />
          <SummaryCard summary={data.summary} range={range} />
        </div>
      )}

      <InsightChartSheet chart={chart} initialRange={range} onClose={() => setChart(null)} />
      <FitnessSheet view={fitnessOpen ? 'status' : null} onClose={() => setFitnessOpen(false)} />
    </>
  )
}
