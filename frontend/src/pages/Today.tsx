import { useEffect, useState, type ReactNode } from 'react'
import { EveningWakeCard } from '../components/alarm/AlarmCards'
import { UpcomingAdjustments } from '../components/adjust/UpcomingAdjustments'
import { TodayInjury } from '../components/injury/DailyPainCheck'
import { RecentReviewCard } from '../components/review/RunReview'
import { PendingCheckins } from '../components/checkin/PendingCheckins'
import { QuickLogRow } from '../components/habits/QuickLogRow'
import { ChipButton } from '../components/ChipButton'
import { RefreshIcon } from '../components/Icons'
import { AvatarButton } from '../components/Kit'
import { MoodCard } from '../components/mood/MoodCard'
import { IllnessHero, TodayMore } from '../components/illness/IllnessEntry'
import { RecoveryCard } from '../components/recovery/RecoveryEntry'
import { ErrorState } from '../components/States'
import { ForecastCard } from '../components/today/ForecastCard'
import { TodayHero } from '../components/today/TodayHero'
import { StaleNotice } from '../components/today/StaleNotice'
import { SyncBanner } from '../components/today/SyncBanner'
import { resolveLayout, type TodayCardKey } from '../components/today/todayLayout'
import { TodaySoFar } from '../components/today/TodaySoFar'
import { ThisWeek } from '../components/today/ThisWeek'
import { WeatherTile } from '../components/today/WeatherCard'
import { WeeklyReportCard } from '../components/today/WeeklyReportCard'
import { WeatherSwapChips } from '../components/weather/WeatherSwapChip'
import { useAuth } from '../lib/AuthContext'
import { parseDate, todayISO } from '../lib/format'
import { preloadTabs } from '../lib/preload'
import { errorText, useHabitSummary, useSync, useWeek } from '../lib/queries'
import { SyncingPill } from '../lib/r16'
import { PullToRefresh, WaitingForRun } from '../lib/r18'
import { useIllness } from '../lib/r17'
import { useSyncing } from '../lib/syncFlag'

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** "3 days smoke-free" next to LOG NOW, only when it means something. */
function SmokeFree() {
  const { athlete } = useAuth()
  const summary = useHabitSummary('4w')
  const s = summary.data?.smoke
  const days = s?.streak?.current_days ?? 0
  if (!s || days <= 0) return null
  if (athlete?.smoke_goal !== 'quit' && !(s.total > 0 || s.streak.best_days > 0)) return null
  return <>{days} {days === 1 ? 'day' : 'days'} smoke-free</>
}

/**
 * R14 §1 Today: one hero card (readiness + today's session + focus), then the cards the
 * athlete chose in Me → Settings → Customise Today (`today_layout`), in their order.
 * Contextual cards (check-ins, review, mood, injury, weather swap, experiment) render
 * only when there is something to act on.
 */
export default function Today() {
  const { athlete } = useAuth()
  const today = todayISO()
  const week = useWeek(today)
  const sync = useSync()
  const syncing = useSyncing()
  const [toast, setToast] = useState('')
  const day = week.data?.days.find((d) => d.date === today)
  const name = (athlete?.display_name || '').split(' ')[0]
  const dateLabel = parseDate(today).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })
  const layout = resolveLayout(athlete?.today_layout)
  // R17 §10: while unwell, a calm rest hero replaces readiness + workout.
  const illness = useIllness().data?.active ?? null

  useEffect(() => { preloadTabs() }, [])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const runSync = () =>
    sync.mutate(undefined, {
      onSuccess: (r) => setToast(r.imported ? `Synced · ${r.imported} new` : 'Up to date'),
      onError: (e) => setToast(errorText(e, 'Sync failed')),
    })

  const cards: Record<TodayCardKey, ReactNode> = {
    weather_swap: <WeatherSwapChips />,
    checkins: <PendingCheckins />,
    injury: <TodayInjury />,
    review: <RecentReviewCard />,
    mood: <MoodCard untilAnswered />,
    weather: <WeatherTile />,
    log: (
      <section className="card">
        <QuickLogRow label="Log now" aside={<SmokeFree />} />
      </section>
    ),
    wake: <EveningWakeCard />,
    so_far: <TodaySoFar />,
    this_week: <ThisWeek week={week.data} />,
    tomorrow: <ForecastCard />,
    adjustments: <UpcomingAdjustments />,
    weekly_report: <WeeklyReportCard />,
  }

  return (
    <div className="page today-page">
      <header className="today-header">
        <div className="grow">
          <span className="lbl today-date-line">{dateLabel}<SyncingPill /></span>
          <h1 className="today-greeting">{greeting()}{name ? `, ${name}` : ''}</h1>
        </div>
        <ChipButton label="Refresh — sync everything from Garmin" onClick={runSync} disabled={syncing} className="chip-plain">
          <RefreshIcon className={syncing ? 'spin' : ''} />
        </ChipButton>
        <TodayMore />
        <AvatarButton />
      </header>
      {toast && <div className="toast" role="status">{toast}</div>}

      {week.isError && !week.data && (
        <ErrorState message={errorText(week.error, 'Today’s plan did not load.')} onRetry={() => week.refetch()} />
      )}
      <PullToRefresh />
      {/* Above everything, including the session. If the watch stopped talking,
          that fact outranks whatever the plan thinks you should do today —
          because the plan was computed from the data that stopped arriving. */}
      <SyncBanner onSync={runSync} />
      <WaitingForRun />
      <StaleNotice onSync={runSync} />
      {illness ? <IllnessHero illness={illness} /> : <TodayHero day={day} loading={week.isPending} />}
      <RecoveryCard />
      {layout.map((key) => <TodaySlot key={key}>{cards[key]}</TodaySlot>)}
    </div>
  )
}

/** Keeps keys stable while each card decides for itself whether to render. */
function TodaySlot({ children }: { children: ReactNode }) {
  return <>{children}</>
}
