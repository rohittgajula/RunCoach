import { useAuth } from '../../lib/AuthContext'
import { ApiError } from '../../lib/auth'
import { errorText, useHabitSummary } from '../../lib/queries'
import type { InsightRange } from '../../lib/types'
import { InsightCard } from '../insights/Tile'
import { ErrorState, Skeleton } from '../States'
import { HabitCharts } from './HabitCharts'
import { HabitSummaryCard } from './HabitSummaryCard'
import { ImpactCards } from './ImpactCards'
import { QuickLogRow } from './QuickLogRow'
import { SinceQuit } from './SinceQuitCard'

/** Insights → Habits: quick log, smoke-free streak, trends, since-quit, impact, AI read. */
export function HabitsSection({ range }: { range: InsightRange }) {
  const { athlete } = useAuth()
  const summary = useHabitSummary(range)
  if (summary.isError && summary.error instanceof ApiError && summary.error.status === 404) return null
  const data = summary.data
  const quitting = athlete?.smoke_goal === 'quit'
  const streak = data?.smoke.streak

  return (
    <InsightCard title="Habits" className="habits">
      <QuickLogRow label="Log now" />
      {summary.isPending && <Skeleton lines={4} />}
      {summary.isError && !data && <ErrorState message={errorText(summary.error, 'Habits did not load.')} onRetry={() => summary.refetch()} />}
      {data && (
        <div className={`stack ${summary.isPlaceholderData ? 'is-stale' : ''}`}>
          {(quitting || data.smoke.total > 0 || (streak?.best_days ?? 0) > 0) && streak && (
            <div className="streak">
              <span className="streak-num">{streak.current_days}</span>
              <div className="grow">
                <p className="streak-label">{streak.current_days === 1 ? 'day' : 'days'} smoke-free</p>
                <p className="muted small">
                  Best: {streak.best_days} {streak.best_days === 1 ? 'day' : 'days'}
                  {data.smoke.trend_per_week != null && data.smoke.total > 0 &&
                    ` · ${data.smoke.trend_per_week > 0 ? '+' : ''}${data.smoke.trend_per_week.toFixed(1)} cigarettes/day per week`}
                </p>
              </div>
            </div>
          )}
          <HabitCharts data={data} />
          {quitting && <SinceQuit smoke={data.smoke} />}
          {quitting && !data.smoke.since_quit && <p className="muted small">Set your quit date in Settings → Habits to track days, cigarettes avoided and money saved.</p>}
          <ImpactCards impact={data.impact ?? []} />
          <HabitSummaryCard summary={data.summary} range={range} />
        </div>
      )}
    </InsightCard>
  )
}
