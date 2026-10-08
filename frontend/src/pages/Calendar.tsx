import { Fragment, lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ActivityCardView, WorkoutCard } from '../components/Cards'
import { ChipButton } from '../components/ChipButton'
import { MonthView } from '../components/calendar/MonthView'
import { ActivitySheet, WorkoutSheet } from '../components/DetailSheets'
import { UpcomingAdjustments } from '../components/adjust/UpcomingAdjustments'
import { WeatherSwapChips } from '../components/weather/WeatherSwapChip'
import { WeekGarminMenu } from '../components/workout/WeekGarminMenu'
import { StrengthCard } from '../components/strength/StrengthCard'
import { CalendarIcon, ChevronDown, ChevronRight, EditIcon, RefreshIcon } from '../components/Icons'
import { PageHeader } from '../components/PageHeader'
import { PhasePill } from '../components/PhasePill'
import { PlanDetailSheet } from '../components/profile/PlanDetailSheet'
import { ErrorState, Loading, Skeleton } from '../components/States'
import { useCoachLaunch } from '../components/useCoachLaunch'
import { addDays, dur, monthDay, parseDate, todayISO, weekday } from '../lib/format'
import { errorText, useActivePlan, useCalendar, useSync, useToday } from '../lib/queries'
import type { ActivityCard, CalDay, CalWeek, Workout } from '../lib/types'

import { BUILD_PLAN_PROMPT } from '../lib/prompts'
import { canEditWorkout } from '../components/edit/EditedChip'
export { BUILD_PLAN_PROMPT }

// R16 §A: "Edit week" is its own chunk (shares the editor's styles and steppers).
const loadWeekEdit = () => import('../components/edit/WeekEditSheet')
const WeekEditSheet = lazy(loadWeekEdit)

/** Plan tab: the month/week calendar and the plan (the pre-R10 Calendar minus today). */
export default function Calendar() {
  const navigate = useNavigate()
  const launch = useCoachLaunch()
  const calendar = useCalendar()
  const activePlan = useActivePlan()
  const sync = useSync()
  const checkin = useToday()
  // Fallback for the "Adjusted" tag if the calendar copy predates `adjusted_by`.
  const adjustedId = checkin.data?.applied ? checkin.data.workout?.id ?? null : null
  const scrollRef = useRef<HTMLDivElement>(null)
  const topRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const anchor = useRef<{ height: number; top: number } | null>(null)
  const [ready, setReady] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [openWorkout, setOpenWorkout] = useState<Workout | null>(null)
  const [openActivity, setOpenActivity] = useState<ActivityCard | null>(null)
  const [toast, setToast] = useState('')
  const [view, setView] = useState<'list' | 'month'>('list')
  const [planOpen, setPlanOpen] = useState(false)
  const [weekEdit, setWeekEdit] = useState<{ week: CalWeek; open: boolean } | null>(null)
  const listScroll = useRef<number | null>(null)

  const pages = calendar.data?.pages
  const today = pages?.[0]?.today ?? todayISO()

  const { days, weeks } = useMemo(() => {
    const byDate = new Map<string, CalDay>()
    const byWeek = new Map<string, CalWeek>()
    for (const page of pages ?? []) {
      for (const day of page.days) byDate.set(day.date, day)
      // A week straddling two windows comes back twice; the later page wins
      // because the server totals the whole week either way.
      for (const week of page.weeks) byWeek.set(week.start, week)
    }
    return {
      days: [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date)),
      weeks: [...byWeek.values()].sort((a, b) => a.start.localeCompare(b.start)),
    }
  }, [pages])

  const weekOf = (date: string) => weeks.find((w) => w.start <= date && date <= w.end)

  /** The week's sessions that can still be edited (R16 §A week tools). */
  const editableIn = (week: CalWeek): Workout[] =>
    days
      .filter((d) => week.start <= d.date && d.date <= week.end && d.date >= today)
      .flatMap((d) => d.items.flatMap((i) => (i.type === 'workout' && canEditWorkout(i.workout) && i.workout.kind?.toLowerCase() !== 'race' ? [i.workout] : [])))

  // Open on today, once.
  useLayoutEffect(() => {
    if (ready || !days.length || view !== 'list') return
    // The morning check-in sits just above today; open on it.
    const el =
      scrollRef.current?.querySelector<HTMLElement>('[data-anchor="today"]') ??
      scrollRef.current?.querySelector<HTMLElement>(`[data-date="${today}"]`)
    el?.scrollIntoView({ block: 'start' })
    setReady(true)
  }, [days.length, ready, today, view])

  // Keep the viewport still when older days are prepended.
  const firstDate = days[0]?.date
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && anchor.current) {
      el.scrollTop = anchor.current.top + (el.scrollHeight - anchor.current.height)
      anchor.current = null
    }
  }, [firstDate])

  useEffect(() => {
    const root = scrollRef.current
    if (!ready || !root) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          if (entry.target === topRef.current && calendar.hasPreviousPage && !calendar.isFetchingPreviousPage) {
            anchor.current = { height: root.scrollHeight, top: root.scrollTop }
            calendar.fetchPreviousPage()
          }
          if (entry.target === bottomRef.current && calendar.hasNextPage && !calendar.isFetchingNextPage) {
            calendar.fetchNextPage()
          }
        }
      },
      { root, rootMargin: '600px 0px' },
    )
    if (topRef.current) observer.observe(topRef.current)
    if (bottomRef.current) observer.observe(bottomRef.current)
    return () => observer.disconnect()
  }, [ready, calendar])

  const runSync = () =>
    sync.mutate(undefined, {
      onSuccess: (result) => setToast(result.imported ? `Synced · ${result.imported} new` : 'Up to date'),
      onError: (error) => setToast(errorText(error, 'Sync failed')),
    })

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 3500)
    return () => clearTimeout(timer)
  }, [toast])

  // The list is this page's scroll root; remember where it was across a month detour.
  const switchView = (next: 'list' | 'month') => {
    if (next === view) return
    if (next === 'month') listScroll.current = scrollRef.current?.scrollTop ?? 0
    setView(next)
  }
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (view === 'month') el.scrollTop = 0
    else if (ready && listScroll.current != null) el.scrollTop = listScroll.current
    // `ready` is read, not tracked: only a view switch should move the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view])

  const toggleWeek = (start: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(start)) next.delete(start)
      else next.add(start)
      return next
    })

  return (
    <div className="page cal-page" ref={scrollRef}>
      <PageHeader
        title="Plan"
        right={
          <>
          <div className="segmented segmented-compact" role="tablist" aria-label="Calendar view">
            {(['list', 'month'] as const).map((option) => (
              <button
                key={option}
                type="button"
                role="tab"
                aria-selected={view === option}
                className={`segmented-option ${view === option ? 'is-active' : ''}`}
                onClick={() => switchView(option)}
              >
                {option === 'list' ? 'List' : 'Month'}
              </button>
            ))}
          </div>
          <ChipButton label="Sync Garmin" onClick={runSync} disabled={sync.isPending} className="chip-plain">
            <RefreshIcon className={sync.isPending ? 'spin' : ''} />
          </ChipButton>
          </>
        }
      />
      {toast && <div className="toast" role="status">{toast}</div>}

      {activePlan.data === null && (
        <section className="card banner">
          <p className="banner-title">No plan yet — ask the coach to build one</p>
          <p className="muted small">Tell it your race or goal. It asks only what it can't work out from your Garmin data.</p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate('/chat/new', { state: { prompt: BUILD_PLAN_PROMPT } })}
          >
            Ask the coach
          </button>
        </section>
      )}

      {activePlan.data && (
        <button type="button" className="card plan-strip" onClick={() => setPlanOpen(true)}>
          <span className="grow">
            <span className="lbl">Your plan</span>
            <span className="plan-strip-name">{activePlan.data.name}</span>
          </span>
          {(() => {
            const phase = activePlan.data.phases.find((p) => p.id === activePlan.data!.current_phase_id)
            return phase ? <PhasePill kind={phase.kind} name={phase.name} /> : null
          })()}
          <ChevronRight size={18} className="muted" />
        </button>
      )}

      {view === 'month' && (
        <MonthView
          today={today}
          onWorkout={setOpenWorkout}
          onActivity={setOpenActivity}
          onGuide={launch.guide}
          onReview={launch.review}
        />
      )}

      <div className="cal-list-wrap" hidden={view !== 'list'}>
      {calendar.isPending && (
        <div className="cal-list">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="cal-day">
              <div className="cal-date"><Skeleton lines={2} /></div>
              <div className="card cal-card"><Skeleton height={i % 2 ? 40 : 110} /></div>
            </div>
          ))}
        </div>
      )}

      {calendar.isError && !pages && (
        <ErrorState message={errorText(calendar.error, 'The calendar did not load.')} onRetry={() => calendar.refetch()} />
      )}

      {pages && (
        <div className="cal-list">
          <div ref={topRef} className="sentinel" />
          {calendar.isFetchingPreviousPage && <Loading label="Loading earlier days…" />}
          {days.map((day, index) => {
            const week = weekOf(day.date)
            // The first loaded day may be mid-week; still give it its header.
            const isWeekStart = !!week && (week.start === day.date || index === 0)
            const hidden = !!week && collapsed.has(week.start)
            return (
              <Fragment key={day.date}>
                {isWeekStart && week && (
                  <WeekHeader
                    week={week}
                    today={today}
                    collapsed={collapsed.has(week.start)}
                    onToggle={() => toggleWeek(week.start)}
                    canSend={!!activePlan.data && week.end >= today && week.start <= addDays(today, 7)}
                    onEdit={activePlan.data && week.end >= today && editableIn(week).length ? () => setWeekEdit({ week, open: true }) : undefined}
                  />
                )}
                {day.date === today && (
                  <div data-anchor="today" className="stack-sm cal-today-extras">
                    <WeatherSwapChips />
                    <UpcomingAdjustments />
                  </div>
                )}
                {!hidden && (
                  <DayRow
                    day={day}
                    isToday={day.date === today}
                    isPast={day.date < today}
                    onWorkout={setOpenWorkout}
                    onActivity={setOpenActivity}
                    onGuide={launch.guide}
                    onReview={launch.review}
                    adjustedId={adjustedId}
                  />
                )}
              </Fragment>
            )
          })}
          {calendar.isFetchingNextPage && <Loading label="Loading more days…" />}
          {calendar.isError && pages && (
            <p className="bad small centered">{errorText(calendar.error, 'Could not load more days.')}</p>
          )}
          <div ref={bottomRef} className="sentinel" />
        </div>
      )}
      </div>

      <WorkoutSheet workout={openWorkout} onClose={() => setOpenWorkout(null)} />
      <PlanDetailSheet planId={planOpen && activePlan.data ? activePlan.data.id : null} onClose={() => setPlanOpen(false)} />
      <ActivitySheet activity={openActivity} onClose={() => setOpenActivity(null)} />
      {weekEdit && (
        <Suspense fallback={null}>
          <WeekEditSheet
            week={weekEdit.week}
            workouts={editableIn(weekEdit.week)}
            open={weekEdit.open}
            onClose={() => setWeekEdit({ ...weekEdit, open: false })}
            onDone={(message) => { setWeekEdit({ ...weekEdit, open: false }); setToast(message) }}
          />
        </Suspense>
      )}
    </div>
  )
}

function WeekHeader({
  week, collapsed, onToggle, today, canSend, onEdit,
}: { week: CalWeek; collapsed: boolean; onToggle: () => void; today: string; canSend: boolean; onEdit?: () => void }) {
  const planned = week.planned_s > 0
  const seconds = planned ? week.planned_s : week.actual_s
  const load = planned ? week.planned_load : week.actual_load
  return (
    <div className="week-head">
      <span className="week-icon"><CalendarIcon size={20} /></span>
      <div className="week-text">
        <p className="week-range">
          {monthDay(week.start)} – {monthDay(week.end)}
        </p>
        <p className="week-totals">
          {seconds ? dur(seconds) : '0m'} · {Math.round(load)} Load
        </p>
        {week.start <= today && (planned || week.actual_s > 0) && (
          <div className="week-progress" aria-label="Done vs planned">
            <span className="week-progress-track">
              <span
                className={`week-progress-fill ${planned && week.actual_s > week.planned_s ? 'is-over' : ''}`}
                style={{ width: `${planned ? Math.min(100, (week.actual_s / week.planned_s) * 100) : 100}%` }}
              />
            </span>
            <span className="week-progress-text">
              {planned ? <>Done {dur(week.actual_s)} of {dur(week.planned_s)}</> : <>Done {dur(week.actual_s)} · no plan</>}
            </span>
          </div>
        )}
        {onEdit && (
          <button type="button" className="week-edit-btn" onClick={onEdit} onPointerDown={() => { void loadWeekEdit() }}>
            <EditIcon size={15} /> Edit week
          </button>
        )}
      </div>
      {canSend && <WeekGarminMenu week={week} today={today} />}
      <button
        type="button"
        className={`icon-btn ${collapsed ? 'is-collapsed' : ''}`}
        aria-label={collapsed ? 'Expand week' : 'Collapse week'}
        aria-expanded={!collapsed}
        onClick={onToggle}
      >
        <ChevronDown />
      </button>
    </div>
  )
}

function DayRow({
  day, isToday, isPast, onWorkout, onActivity, onGuide, onReview, adjustedId,
}: {
  day: CalDay
  isToday: boolean
  isPast: boolean
  onWorkout: (w: Workout) => void
  onActivity: (a: ActivityCard) => void
  onGuide: (w: Workout) => void
  onReview: (a: ActivityCard) => void
  adjustedId: number | null
}) {
  return (
    <div className={`cal-day ${isPast ? 'is-past' : ''}`} data-date={day.date}>
      <div className={`cal-date ${isToday ? 'is-today' : ''}`}>
        <span className="cal-dow">{weekday(day.date)}</span>
        <span className="cal-dom">{parseDate(day.date).getDate()}</span>
      </div>
      <div className="cal-items">
        {day.items.length === 0 && (isToday
          ? <div className="card cal-card cal-rest">{day.rest ?? 'Rest'}</div>
          : <div className="cal-rest-line">{day.rest ?? 'Rest'}</div>)}
        {day.items.map((item) =>
          item.type === 'workout' ? (
            <WorkoutCard
              key={`w${item.workout.id}`}
              workout={item.workout}
              adjusted={item.workout.id === adjustedId}
              compact={!isToday}
              onOpen={() => onWorkout(item.workout)}
              onGuide={() => onGuide(item.workout)}
            />
          ) : item.type === 'strength' ? (
            <StrengthCard key={`s${item.strength.id}`} session={item.strength} compact={!isToday} />
          ) : (
            <ActivityCardView
              key={`a${item.activity.id}`}
              activity={item.activity}
              compact={!isToday}
              onOpen={() => onActivity(item.activity)}
              onReview={() => onReview(item.activity)}
            />
          ),
        )}
      </div>
    </div>
  )
}
