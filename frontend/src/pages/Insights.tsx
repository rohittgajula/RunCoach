import { useState } from 'react'
import { ChipButton } from '../components/ChipButton'
import { TodayCard } from '../components/checkin/TodayCard'
import { GearIcon } from '../components/Icons'
import { FitnessSheet } from '../components/profile/FitnessSheet'
import { PageHeader } from '../components/PageHeader'
import { RangeSwitch } from '../components/RangeSwitch'
import { useShell } from '../components/Shell'
import { ErrorState, Skeleton } from '../components/States'
import { FocusCard, LoadCard, SummaryCard } from '../components/insights/AdviceCards'
import { INSIGHT_RANGES, InsightChartSheet } from '../components/insights/InsightChartSheet'
import { BreathingCard, FitnessCard, RecoveryCard } from '../components/insights/RecoveryCards'
import { ReadinessCard, RunningCard } from '../components/insights/RunningCards'
import type { ChartKey } from '../components/insights/charts'
import { errorText, useInsights } from '../lib/queries'
import type { InsightRange } from '../lib/types'

export default function Insights() {
  const { openSettings } = useShell()
  const [range, setRange] = useState<InsightRange>('4w')
  const [chart, setChart] = useState<ChartKey | null>(null)
  const [fitnessOpen, setFitnessOpen] = useState(false)
  const insights = useInsights(range)
  const data = insights.data

  return (
    <div className="page insights-page">
      <PageHeader
        title="Insights"
        right={
          <ChipButton label="Settings" onClick={openSettings}>
            <GearIcon />
          </ChipButton>
        }
      />
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
          <RecoveryCard data={data} onChart={setChart} />
          <BreathingCard data={data} onChart={setChart} />
          <FitnessCard data={data} onChart={setChart} />
          <LoadCard load={data.load} onOpen={() => setFitnessOpen(true)} />
          <FocusCard focus={data.focus ?? []} hasRuns={(data.running?.runs ?? 0) > 0} />
          <SummaryCard summary={data.summary} range={range} />
        </div>
      )}

      <InsightChartSheet chart={chart} initialRange={range} onClose={() => setChart(null)} />
      <FitnessSheet view={fitnessOpen ? 'status' : null} onClose={() => setFitnessOpen(false)} />
    </div>
  )
}
