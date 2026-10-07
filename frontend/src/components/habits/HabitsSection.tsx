import { Disclosure } from '../Disclose'
import { useState } from 'react'
import { useAuth } from '../../lib/AuthContext'
import { ApiError } from '../../lib/auth'
import { errorText, useHabitSummary, useLogHabit } from '../../lib/queries'
import type { HabitKind, HabitReportHabit, HabitSummary } from '../../lib/types'
import { InsightCard } from '../insights/Tile'
import { FREQ_NOUN, bucket, periodCaption, useHealthPeriod, withApiPeriod, type Freq } from '../health/healthRange'
import { Empty, ErrorState, Skeleton } from '../States'
import { HabitCard } from './HabitCard'
import { HabitSummaryCard } from './HabitSummaryCard'
import { HealthReportCard } from './HealthReportCard'
import { ImpactCards } from './ImpactCards'
import { LogHistory } from './LogHistory'
import { LungRecoveryCard } from './LungRecoveryCard'
import { QuickLogRow } from './QuickLogRow'
import { SinceQuit } from './SinceQuitCard'
import { CaffeineCard } from './CaffeineCard'
import { CravingPatternsCard, SavingsGoalCard } from '../quit/QuitCards'
import { HABITS, PRIVATE_HABIT, PRIVATE_SHOWN_KEY, habitMeta, readFlag, writeFlag } from './habitUtil'

const fmt = (v: number | null | undefined, digits = 1) => (v == null ? '--' : v.toFixed(digits))
const COLORS: Record<HabitKind, string> = { smoke: 'var(--habits)', alcohol: 'var(--habits)', sugar: 'var(--habits)', private: 'var(--habits)', caffeine: 'var(--habits)' }

/** Insights → Habits: range, health report, a card per habit, since-quit, impact, AI, history. */
export function HabitsPage() {
  const { athlete } = useAuth()
  const { period: chosen } = useHealthPeriod()
  const [privateShown, setPrivateShown] = useState(() => readFlag(PRIVATE_SHOWN_KEY))
  const range = chosen.params
  const summary = useHabitSummary(range)
  const data = summary.data
  const period = withApiPeriod(chosen, data?.period)
  const freq = period.freq
  const caption = periodCaption(period)

  if (summary.isError && summary.error instanceof ApiError && summary.error.status === 404) {
    return <Empty title="Habits aren’t available yet">Check back after the next update.</Empty>
  }

  const togglePrivate = (on: boolean) => {
    setPrivateShown(on)
    writeFlag(PRIVATE_SHOWN_KEY, on)
  }

  const report = data?.report
  const entry = (kind: HabitKind): HabitReportHabit | undefined => report?.habits?.find((h) => h.habit === kind)
  const goals: Record<string, string | undefined> = { smoke: athlete?.smoke_goal, alcohol: athlete?.alcohol_goal, sugar: athlete?.sugar_goal }
  const visible = data
    ? HABITS.filter((h) => entry(h.kind) || totalOf(data, h.kind) > 0 || (goals[h.kind] && goals[h.kind] !== 'none'))
    : []
  // The server omits `private` entirely while it is disabled.
  const hasPrivate = !!data && (data.private != null || !!entry('private')) && athlete?.private_habit_enabled !== false
  const historyKinds = hasPrivate && privateShown ? [...HABITS, PRIVATE_HABIT] : HABITS
  const quitting = athlete?.smoke_goal === 'quit'

  return (
    <div className="stack">
      <section className="card habits-log">
        <QuickLogRow label="Log now" />
      </section>

      {summary.isPending && [0, 1].map((i) => <section key={i} className="card"><Skeleton lines={4} /></section>)}
      {summary.isError && !data && <ErrorState message={errorText(summary.error, 'Habits did not load.')} onRetry={() => summary.refetch()} />}

      {data && (
        <div className={`stack ${summary.isPlaceholderData ? 'is-stale' : ''}`}>
          <HealthReportCard report={report} rangeLabel={chosen.selection.kind === 'preset' ? chosen.long : `${period.days} days`} />

          {visible.map((h) => (
            <HabitCard
              key={h.kind}
              meta={h}
              title={h.kind === 'smoke' ? 'Smoking' : h.kind === 'alcohol' ? 'Alcohol' : 'Sugar'}
              entry={entry(h.kind)}
              points={pointsOf(data, h.kind, freq)}
              chartTitle={`${h.kind === 'alcohol' ? 'Drinks' : h.kind === 'smoke' ? 'Cigarettes' : 'Servings'} per ${h.kind === 'alcohol' && freq === 'day' ? 'week' : FREQ_NOUN[freq]}`}
              freq={h.kind === 'alcohol' && freq === 'day' ? 'week' : freq}
              period={caption}
              sub={subOf(data, h.kind)}
              color={COLORS[h.kind]}
            >
              {h.kind === 'smoke' && <Streak data={data} quitting={quitting} />}
            </HabitCard>
          ))}
          {!visible.length && !hasPrivate && (
            <section className="card">
              <p className="muted small">Nothing logged in this range yet. Tap the buttons above when it happens — honest logs make the report useful.</p>
            </section>
          )}

          {hasPrivate && (
            <PrivateCard data={data} entry={entry('private')} shown={privateShown} onToggle={togglePrivate} />
          )}

          {/* R14 §1: the deeper cards are grouped and collapsed. */}
          {(quitting || athlete?.smoke_goal === 'reduce' || !!athlete?.smoke_quit_date) && (
            <Disclosure id="habits-quit" title="Quitting & savings" sub="Since you quit, cravings, money saved, lung recovery">
            {quitting && (
              <InsightCard title="Since you quit">
                {data.smoke.since_quit ? (
                  <SinceQuit smoke={data.smoke} title={false} />
                ) : (
                  <p className="muted small">Set your quit date in Settings → Habits to track days, cigarettes avoided and money saved.</p>
                )}
              </InsightCard>
            )}

            {(quitting || athlete?.smoke_goal === 'reduce') && <CravingPatternsCard range={range} />}
            <SavingsGoalCard />

            <LungRecoveryCard enabled={!!athlete?.smoke_quit_date} />

            </Disclosure>
          )}
          {!(quitting || athlete?.smoke_goal === 'reduce' || !!athlete?.smoke_quit_date) && <SavingsGoalCard />}

          <Disclosure id="habits-caffeine" title="Caffeine" sub="How much, how late — and your sleep">
            <CaffeineCard range={range} freq={freq} period={caption} />
          </Disclosure>

          <Disclosure id="habits-impact" title="Impact, coach summary & history" sub="How habits moved your HRV, sleep and runs">
            <InsightCard title="Impact detail">
              <ImpactCards impact={data.impact ?? []} hidePrivate={!privateShown} title={false} />
            </InsightCard>

            <section className="card">
              <HabitSummaryCard summary={data.summary} range={range} />
            </section>

            <LogHistory start={period.start} end={period.end} kinds={historyKinds} />
          </Disclosure>
        </div>
      )}
    </div>
  )
}

function totalOf(data: HabitSummary, kind: HabitKind): number {
  if (kind === 'private') return data.private?.total ?? 0
  if (kind === 'caffeine') return 0
  return data[kind]?.total ?? 0
}

/** Counts per bucket (sums). Alcohol stays per week at daily frequency, as before R12. */
function pointsOf(data: HabitSummary, kind: HabitKind, freq: Freq) {
  const sum = (pts: Array<{ date: string; value: number }>, f: Freq) =>
    bucket(pts, f, 'sum').map((p) => ({ date: p.date, value: p.value ?? 0 }))
  if (kind === 'alcohol') {
    const daily = data.alcohol.series.map((p) => ({ date: p.date, value: p.count }))
    const weekly = data.weekly?.map((w) => ({ date: w.week_start, value: w.drinks })) ?? []
    if (freq === 'month') return sum(daily.length ? daily : weekly, 'month')
    return weekly.length ? weekly : sum(daily, 'week')
  }
  if (kind === 'caffeine') return []
  const series = kind === 'private' ? data.private?.series ?? [] : data[kind].series
  return sum(series.map((p) => ({ date: p.date, value: p.count })), freq)
}

function subOf(data: HabitSummary, kind: HabitKind): string {
  if (kind === 'alcohol') {
    const d = data.alcohol.drink_days
    return `avg ${fmt(data.alcohol.per_week_avg)}/week · ${d} drink ${d === 1 ? 'day' : 'days'}`
  }
  if (kind === 'caffeine') return ''
  const avg = kind === 'private' ? data.private?.per_day_avg : data[kind].per_day_avg
  return `avg ${fmt(avg)}/day`
}

function Streak({ data, quitting }: { data: HabitSummary; quitting: boolean }) {
  const streak = data.smoke.streak
  if (!streak || !(quitting || data.smoke.total > 0 || streak.best_days > 0)) return null
  return (
    <div className="streak">
      <span className="streak-num">{streak.current_days}</span>
      <div className="grow">
        <p className="streak-label">{streak.current_days === 1 ? 'day' : 'days'} smoke-free</p>
        <p className="muted small">Best: {streak.best_days} {streak.best_days === 1 ? 'day' : 'days'}</p>
      </div>
    </div>
  )
}

/** 🌙 Private: collapsed and blurred until tapped; the choice is remembered on this device. */
function PrivateCard({
  data, entry, shown, onToggle,
}: { data: HabitSummary; entry: HabitReportHabit | undefined; shown: boolean; onToggle: (on: boolean) => void }) {
  const log = useLogHabit()
  const [logged, setLogged] = useState(false)
  if (!shown) {
    return (
      <section className="card insight private-card is-hidden">
        <div className="card-head">
          <h2 className="card-title habit-card-title"><span aria-hidden="true">🌙</span> Private</h2>
        </div>
        <button type="button" className="private-cover" onClick={() => onToggle(true)}>
          <span className="private-blur" aria-hidden="true">
            <span /><span /><span />
          </span>
          <span className="private-tap">Tap to show</span>
        </button>
      </section>
    )
  }
  return (
    <HabitCard
      className="private-card"
      meta={PRIVATE_HABIT}
      entry={entry}
      points={pointsOf(data, 'private', 'day')}
      chartTitle="Per day"
      sub={subOf(data, 'private')}
      color={COLORS.private}
      aside={
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => onToggle(false)}>Hide</button>
      }
    >
      <div className="row-end">
        {logged && !log.isPending && <span className="muted small">{habitMeta('private').emoji} logged</span>}
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={log.isPending}
          onClick={() => log.mutate({ kind: 'private', quantity: 1 }, { onSuccess: () => setLogged(true) })}
        >
          {log.isPending ? 'Logging…' : '+1 🌙'}
        </button>
      </div>
      {log.isError && <p className="bad small">{errorText(log.error, 'Could not log that.')}</p>}
    </HabitCard>
  )
}
