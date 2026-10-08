import {
  infiniteQueryOptions, queryOptions, useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient,
} from '@tanstack/react-query'
import { ApiError, api, json } from './auth'
import { addDays, todayISO } from './format'
import { setSyncing } from './syncFlag'
import type {
  ActivityCard, CalendarResponse, DietDay, DietTrend, FitnessResponse, GarminStatus,
  Meal, MealEstimate, MemoryFact, Message, MetricEntriesResponse, MetricEntry, MetricKind,
  Plan, PlanSummary, ProfileSummary, Race, Range, SendResult, Thread, ThreadListItem,
  Workout, AttachmentRef, SyncResult, CoachReview, InsightRange, Insights, MonthResponse,
  WorkoutActual, Compliance, TodayCheckin, PendingCheckin, CheckinBody, CheckinEntry,
  GarminSendResult, HabitKind, HabitLog, HabitLogBody, HabitSummary, HabitSummaryText,
  HabitToday, Progress, ProgressReview, ProgressQuery, WeatherToday, GuidesResponse,
  HealthFitness, TrainingStatus, HealthSleep, HealthForm, HealthRecords, GearResponse, Shoe,
  LungRecovery, WeeklyReport, WeeklyReportListItem, CompareMetric, CompareResult,
  RemindersResponse, Reminder, Achievements, ReadinessForecast, HealthBody,
  HealthDay, DaySummary, DayTrends, ActivityRoute, WaterDay, WaterLog, Nudge,
  WakePlan, MyAlarm, WatchAlarms,
} from './types'

export const errorText = (error: unknown, fallback = 'Something went wrong.'): string =>
  error instanceof ApiError ? error.message : fallback

/** Everything that depends on the plan. Accepting/declining/moving touches all of it. */
export function invalidatePlanData(client: QueryClient) {
  for (const key of ['calendar', 'calendar-month', 'calendar-day', 'plan-active', 'plans', 'plan', 'profile-summary', 'diet-day', 'workout', 'wake-plan']) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

// --- profile ---------------------------------------------------------------------

export const useProfileSummary = () =>
  useQuery({ queryKey: ['profile-summary'], queryFn: () => api<ProfileSummary>('/profile/summary/') })

export const useFitness = (range: Range) =>
  useQuery({
    queryKey: ['fitness', range],
    queryFn: () => api<FitnessResponse>(`/metrics/fitness/?range=${range}`),
    placeholderData: (previous) => previous,
  })

export const useMetricEntries = (kind: MetricKind, range: Range) =>
  useQuery({
    queryKey: ['metric', kind, range],
    queryFn: () => api<MetricEntriesResponse>(`/metrics/entries/?kind=${kind}&range=${range}`),
    placeholderData: (previous) => previous,
  })

export function useAddMetric() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { kind: MetricKind; value: number; recorded_at?: string }) =>
      api<MetricEntry>('/metrics/entries/', { method: 'POST', ...json(body) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['metric'] })
      client.invalidateQueries({ queryKey: ['profile-summary'] })
      client.invalidateQueries({ queryKey: ['diet-day'] })
    },
  })
}

export function useDeleteMetric() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/metrics/entries/${id}/`, { method: 'DELETE' }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['metric'] })
      client.invalidateQueries({ queryKey: ['profile-summary'] })
    },
  })
}

// --- plans -----------------------------------------------------------------------

const activePlanQuery = queryOptions({
  queryKey: ['plan-active'],
  queryFn: async () => {
    try {
      return await api<Plan>('/plans/active/')
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  },
})

export const useActivePlan = () => useQuery(activePlanQuery)

export const usePlan = (id: number | null) =>
  useQuery({
    queryKey: ['plan', id],
    queryFn: () => api<Plan>(`/plans/${id}/`),
    enabled: id != null,
  })

export function usePlanDecision() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: 'accept' | 'decline' }) =>
      api<Plan>(`/plans/${id}/${decision}/`, { method: 'POST' }),
    onSuccess: () => {
      invalidatePlanData(client)
      client.invalidateQueries({ queryKey: ['messages'] })
    },
  })
}

// --- calendar --------------------------------------------------------------------

type Window = { start: string; end: string }
const SPAN = 14

const calendarQuery = (today: string) =>
  infiniteQueryOptions({
    queryKey: ['calendar'],
    initialPageParam: { start: addDays(today, -SPAN), end: addDays(today, SPAN) } as Window,
    queryFn: ({ pageParam }) =>
      api<CalendarResponse>(`/calendar/?start=${pageParam.start}&end=${pageParam.end}`),
    getNextPageParam: (_last, _all, param) => ({ start: addDays(param.end, 1), end: addDays(param.end, SPAN) }),
    getPreviousPageParam: (_first, _all, param) => ({ start: addDays(param.start, -SPAN), end: addDays(param.start, -1) }),
    // Each page is ~29 days; keep enough to scroll a season either way.
    maxPages: 14,
  })

export function useCalendar() {
  return useInfiniteQuery(calendarQuery(todayISO()))
}

/** Monday of the week containing `iso` (athlete-local). */
export function weekStart(iso: string): string {
  const day = (new Date(`${iso}T00:00:00`).getDay() + 6) % 7
  return addDays(iso, -day)
}

/** R10 Today: this week's days (Mon–Sun) — today's workout, the week ring. */
export const useWeek = (date: string = todayISO()) => {
  const start = weekStart(date)
  return useQuery({
    queryKey: ['calendar', 'week', start],
    queryFn: () => api<CalendarResponse>(`/calendar/?start=${start}&end=${addDays(start, 6)}`),
  })
}

export const useWorkout = (id: number | null, initial?: Workout) =>
  useQuery({
    queryKey: ['workout', id],
    queryFn: () => api<Workout>(`/workouts/${id}/`),
    enabled: id != null,
    initialData: initial,
    staleTime: 0,
  })

export function usePatchWorkout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; date?: string; status?: string }) =>
      api<Workout>(`/workouts/${id}/`, { method: 'PATCH', ...json(body) }),
    onSuccess: () => invalidatePlanData(client),
  })
}

/** Guide / Review both create a thread plus the first exchange (slow — 5–30 s). */
export const startGuide = (workoutId: number) =>
  api<{ thread_id: number }>(`/workouts/${workoutId}/guide/`, { method: 'POST' })

export const startReview = (activityId: number) =>
  api<{ thread_id: number }>(`/activities/${activityId}/review/`, { method: 'POST' })

export function useSync() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      setSyncing(true)
      try {
        return await api<SyncResult>('/garmin/sync/', { method: 'POST', ...json({ limit: 20 }) })
      } finally {
        setSyncing(false)
      }
    },
    onSuccess: () => {
      // R16 §C: the dated day metrics and the auto-sync gate read these.
      for (const key of ['sync-status', 'briefing', 'health-day', 'health-day-summary', 'health-body', 'adjustments']) client.invalidateQueries({ queryKey: [key] })
      client.invalidateQueries({ queryKey: ['garmin-status'] })
      client.invalidateQueries({ queryKey: ['calendar'] })
      client.invalidateQueries({ queryKey: ['profile-summary'] })
      client.invalidateQueries({ queryKey: ['diet-day'] })
      client.invalidateQueries({ queryKey: ['calendar-month'] })
      client.invalidateQueries({ queryKey: ['insights'] })
      client.invalidateQueries({ queryKey: ['today'] })
      client.invalidateQueries({ queryKey: ['checkins-pending'] })
      for (const key of ['health-fitness', 'training-status', 'health-sleep', 'health-form', 'health-records', 'readiness-forecast', 'achievements', 'gear', 'lung-recovery', 'progress', 'habits-summary']) {
        client.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}

// --- R6: month calendar, coach review ------------------------------------------------

export const useCalendarMonth = (month: string, enabled = true) =>
  useQuery({
    queryKey: ['calendar-month', month],
    queryFn: () => api<MonthResponse>(`/calendar/month/?month=${month}`),
    placeholderData: (previous) => previous,
    enabled,
  })

/** One day's full items (workouts + activity cards) — the month grid only has summaries. */
export const fetchCalendarDay = (client: QueryClient, date: string) =>
  client.fetchQuery({
    queryKey: ['calendar-day', date],
    queryFn: () => api<CalendarResponse>(`/calendar/?start=${date}&end=${date}`),
    staleTime: 30_000,
  })

/** AI review of a completed workout. Slow (model call); the server caches it. */
export function useWorkoutReview(workoutId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<CoachReview | Workout>(`/workouts/${workoutId}/review/`, { method: 'POST' }),
    onSuccess: (data) => {
      // Accept either the review itself or the whole workout back.
      const review = 'summary_md' in data ? data : data.review
      if (review) {
        client.setQueryData<Workout>(['workout', workoutId], (old) => (old ? { ...old, review } : old))
      }
      client.invalidateQueries({ queryKey: ['workout', workoutId] })
      client.invalidateQueries({ queryKey: ['calendar'] })
    },
  })
}

/** Existing /activities/{id}/ detail (segments + metrics) for the activity sheet. */
export type ActivityDetail = {
  id: number
  avg_hr: number | null
  max_hr: number | null
  total_distance_m: number
  metrics: {
    run_pace_s_per_km: number | null
    avg_run_hr: number | null
    hr_drift_percent: number | null
    longest_run_m: number
  } | null
  segments?: Array<{
    index: number
    kind: 'run' | 'walk' | 'stop'
    duration_s: number
    distance_m: number
    avg_pace_s_per_km: number | null
    hr_avg: number | null
  }>
  /** R6 §3 — every run carries the actual block + review; linked ones also compliance. */
  actual?: WorkoutActual | null
  review?: CoachReview | null
  unplanned?: boolean
  workout_id?: number | null
  compliance?: Compliance | null
  /** R7 §2 — the post-run check-in, when one exists (field name assumed). */
  checkin?: CheckinEntry | null
}

export const useActivityDetail = (id: number | null) =>
  useQuery({
    queryKey: ['activity', id],
    queryFn: () => api<ActivityDetail>(`/activities/${id}/`),
    enabled: id != null,
    retry: false,
  })

/** R6 §3 AI review for any run (unplanned ones have no workout to hang it on). */
export function useActivityAiReview(activityId: number | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<ActivityDetail>(`/activities/${activityId}/ai-review/`, { method: 'POST' }),
    onSuccess: (data) => {
      client.setQueryData(['activity', activityId], data)
      client.invalidateQueries({ queryKey: ['workout'] })
    },
  })
}

export type { ActivityCard }

// --- chat ------------------------------------------------------------------------

const threadsQuery = queryOptions({ queryKey: ['threads'], queryFn: () => api<ThreadListItem[]>('/chat/threads/') })
export const useThreads = () => useQuery(threadsQuery)

export const useMessages = (threadId: number | null) =>
  useQuery({
    queryKey: ['messages', threadId],
    queryFn: () => api<Message[]>(`/chat/threads/${threadId}/messages/`),
    enabled: threadId != null,
  })

export const createThread = (title?: string) =>
  api<Thread>('/chat/threads/', { method: 'POST', ...json(title ? { title } : {}) })

export const sendMessage = (threadId: number, content: string, attachments?: AttachmentRef[]) =>
  api<SendResult>(`/chat/threads/${threadId}/messages/`, {
    method: 'POST',
    ...json(attachments?.length ? { content, attachments } : { content }),
  })

export function useRenameThread() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api<Thread>(`/chat/threads/${id}/`, { method: 'PATCH', ...json({ title }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['threads'] }),
  })
}

export function useDeleteThread() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/chat/threads/${id}/`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['threads'] }),
  })
}

// --- memory ----------------------------------------------------------------------

export const useMemory = (enabled = true) =>
  useQuery({ queryKey: ['memory'], queryFn: () => api<MemoryFact[]>('/memory/'), enabled })

export function useAddMemory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => api<MemoryFact>('/memory/', { method: 'POST', ...json({ text }) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['memory'] })
      client.invalidateQueries({ queryKey: ['profile-summary'] })
    },
  })
}

export function useDeleteMemory() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/memory/${id}/`, { method: 'DELETE' }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['memory'] })
      client.invalidateQueries({ queryKey: ['profile-summary'] })
    },
  })
}

// --- diet ------------------------------------------------------------------------

const dietDayQuery = (date: string) =>
  queryOptions({ queryKey: ['diet-day', date], queryFn: () => api<DietDay>(`/diet/day/?date=${date}`) })

export const useDietDay = (date: string) =>
  useQuery({ ...dietDayQuery(date), placeholderData: (previous) => previous })

/**
 * Smooth UI: fetch the first screen's data of a tab before it is shown — on the finger
 * touching the tab, and once at idle after launch — so a first visit opens on content
 * rather than skeletons. Fresh data (staleTime) is not refetched.
 */
export function prefetchTab(client: QueryClient, path: string) {
  const top = path.split('/')[1]
  const quiet = (p: Promise<unknown>) => { p.catch(() => undefined) }
  if (top === 'plan') {
    quiet(client.prefetchInfiniteQuery(calendarQuery(todayISO())))
    quiet(client.prefetchQuery(activePlanQuery))
  } else if (top === 'chat') {
    quiet(client.prefetchQuery(threadsQuery))
  } else if (top === 'diet') {
    quiet(client.prefetchQuery(dietDayQuery(todayISO())))
  }
}

export const useDietTrend = (range: Range) =>
  useQuery({
    queryKey: ['diet-trend', range],
    queryFn: () => api<DietTrend>(`/diet/trend/?range=${range}`),
    placeholderData: (previous) => previous,
  })

export const estimateMeal = (input: { text?: string; photo?: File | null; meal_type?: string }) => {
  const form = new FormData()
  if (input.text) form.append('text', input.text)
  if (input.photo) form.append('photo', input.photo)
  if (input.meal_type) form.append('meal_type', input.meal_type)
  return api<MealEstimate>('/diet/meals/estimate/', { method: 'POST', body: form })
}

export type MealDraft = Pick<Meal, 'meal_type' | 'eaten_at' | 'description' | 'items' | 'source'> & {
  photo?: File | null
}

export function useSaveMeal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, draft }: { id?: number; draft: MealDraft }) => {
      if (id != null) {
        // Edits never change the photo; JSON keeps items a real list.
        const { photo: _photo, ...body } = draft
        void _photo
        return api<Meal>(`/diet/meals/${id}/`, { method: 'PATCH', ...json(body) })
      }
      const form = new FormData()
      form.append('meal_type', draft.meal_type)
      form.append('eaten_at', draft.eaten_at)
      form.append('description', draft.description)
      form.append('items', JSON.stringify(draft.items))
      form.append('source', draft.source)
      if (draft.photo) form.append('photo', draft.photo)
      return api<Meal>('/diet/meals/', { method: 'POST', body: form })
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['diet-day'] })
      client.invalidateQueries({ queryKey: ['diet-trend'] })
    },
  })
}

export function useDeleteMeal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/diet/meals/${id}/`, { method: 'DELETE' }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['diet-day'] })
      client.invalidateQueries({ queryKey: ['diet-trend'] })
    },
  })
}

// --- races (existing endpoints) ----------------------------------------------------

export const useRaces = () => useQuery({ queryKey: ['races'], queryFn: () => api<Race[]>('/races/') })

export function useSaveRace() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (race: Omit<Race, 'id'> & { id?: number }) => {
      const { id, ...body } = race
      return id != null
        ? api<Race>(`/races/${id}/`, { method: 'PATCH', ...json(body) })
        : api<Race>('/races/', { method: 'POST', ...json(body) })
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['races'] })
      client.invalidateQueries({ queryKey: ['race-plan'] })
      invalidatePlanData(client)
    },
  })
}

export function useDeleteRace() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/races/${id}/`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['races'] }),
  })
}

// --- insights (R6 §5) -------------------------------------------------------------

/**
 * R12: Health reads take a period — a preset (`'4w'`, sent as `range=4w`) or the full
 * query from the range control (`range=4w&freq=day` / `start=…&end=…&freq=week`).
 */
export type PeriodQuery = string
export const periodQs = (p: PeriodQuery) => (p.includes('=') ? p : `range=${p}`)

export const insightsQuery = (range: PeriodQuery | InsightRange) =>
  queryOptions({ queryKey: ['insights', periodQs(range)], queryFn: () => api<Insights>(`/insights/?${periodQs(range)}`) })

export const useInsights = (range: PeriodQuery | InsightRange) =>
  useQuery({ ...insightsQuery(range), placeholderData: (previous) => previous })

/** Cached per day server-side; `refresh` rewrites today's overview. */
export function useInsightsSummary(range: PeriodQuery | InsightRange) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<NonNullable<Insights['summary']>>(`/insights/summary/?${periodQs(range)}${refresh ? '&refresh=1' : ''}`, { method: 'POST' }),
    onSuccess: (summary) => {
      if (summary && 'markdown' in summary) {
        client.setQueriesData<Insights>({ queryKey: ['insights'] }, (old) => (old ? { ...old, summary } : old))
      } else {
        client.invalidateQueries({ queryKey: ['insights'] })
      }
    },
  })
}

// --- R7: morning check-in -----------------------------------------------------------

export const useToday = () =>
  useQuery({ queryKey: ['today'], queryFn: () => api<TodayCheckin>('/today/'), retry: false })

/** POST /today/apply/ → /today/ with `applied: true`; today's workout steps change. */
export function useApplyToday() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<TodayCheckin>('/today/apply/', { method: 'POST' }),
    onSuccess: (data) => {
      if (data && 'verdict' in data) client.setQueryData(['today'], data)
      invalidatePlanData(client)
      client.invalidateQueries({ queryKey: ['today'] })
    },
  })
}

/** Lite-tier one-liner, cached per day server-side. Accepts /today/ or the explanation back. */
export function useExplainToday() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<TodayCheckin | NonNullable<TodayCheckin['explanation']>>('/today/explain/', { method: 'POST' }),
    onSuccess: (data) => {
      if ('verdict' in data) client.setQueryData(['today'], data)
      else client.setQueryData<TodayCheckin>(['today'], (old) => (old ? { ...old, explanation: data } : old))
    },
  })
}

// --- R7: post-run check-in -----------------------------------------------------------

export const usePendingCheckins = () =>
  useQuery({
    queryKey: ['checkins-pending'],
    queryFn: () => api<PendingCheckin[]>('/checkins/pending/'),
    retry: false,
  })

function invalidateCheckin(client: QueryClient, activityId: number) {
  client.invalidateQueries({ queryKey: ['checkins-pending'] })
  client.invalidateQueries({ queryKey: ['activity', activityId] })
  client.invalidateQueries({ queryKey: ['calendar'] })
  client.invalidateQueries({ queryKey: ['today'] })
}

export function useSubmitCheckin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ activityId, body }: { activityId: number; body: CheckinBody }) =>
      api<CheckinEntry>(`/activities/${activityId}/checkin/`, { method: 'POST', ...json(body) }),
    onSuccess: (entry, { activityId }) => {
      // Drop it from the pending list straight away so the next prompt is correct.
      client.setQueryData<PendingCheckin[]>(['checkins-pending'], (old) => old?.filter((p) => p.activity.id !== activityId))
      client.setQueryData<ActivityDetail>(['activity', activityId], (old) => (old ? { ...old, checkin: entry } : old))
      invalidateCheckin(client, activityId)
    },
  })
}

export function useSkipCheckin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ activityId, reason }: { activityId: number; reason: string }) =>
      api(`/activities/${activityId}/checkin/skip/`, { method: 'POST', ...json({ reason }) }),
    onSuccess: (_data, { activityId }) => {
      client.setQueryData<PendingCheckin[]>(['checkins-pending'], (old) => old?.filter((p) => p.activity.id !== activityId))
      invalidateCheckin(client, activityId)
    },
  })
}

// --- R7: send to Garmin ---------------------------------------------------------------

/** Upload (or re-upload when steps changed) one workout and schedule it on its date. */
export function useSendWorkoutToGarmin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<Workout | GarminSendResult>(`/workouts/${id}/garmin/`, { method: 'POST' }),
    onSuccess: (data, id) => {
      if ('steps' in data) client.setQueryData(['workout', id], data)
      client.invalidateQueries({ queryKey: ['workout', id] })
      client.invalidateQueries({ queryKey: ['calendar'] })
    },
  })
}

export function useRemoveWorkoutFromGarmin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<Workout | null>(`/workouts/${id}/garmin/`, { method: 'DELETE' }),
    onSuccess: (_data, id) => {
      client.invalidateQueries({ queryKey: ['workout', id] })
      client.invalidateQueries({ queryKey: ['calendar'] })
    },
  })
}

/** POST /plans/active/garmin/ {days} → per-workout results (list or `{results}`). */
export function useSendDaysToGarmin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (days: number) => {
      try {
        const data = await api<{ results: GarminSendResult[] }>('/plans/active/garmin/', { method: 'POST', ...json({ days }) })
        return data?.results ?? []
      } catch (error) {
        // 502 = some workouts failed: still show every per-workout result.
        const detail = error instanceof ApiError ? (error.detail as { results?: GarminSendResult[] } | null) : null
        if (error instanceof ApiError && error.status === 502 && detail?.results?.length) return detail.results
        throw error
      }
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['calendar'] })
      client.invalidateQueries({ queryKey: ['workout'] })
    },
  })
}

// --- garmin ----------------------------------------------------------------------

export const useGarminStatus = () =>
  useQuery({ queryKey: ['garmin-status'], queryFn: () => api<GarminStatus>('/garmin/status/'), retry: false })

export type { PlanSummary }

// --- R8 §B: habits ---------------------------------------------------------------------

export const useHabitsToday = () =>
  useQuery({ queryKey: ['habits-today'], queryFn: () => api<HabitToday>('/habits/today/'), retry: false })

export const useHabitSummary = (range: PeriodQuery | InsightRange) =>
  useQuery({
    queryKey: ['habits-summary', periodQs(range)],
    queryFn: () => api<HabitSummary>(`/habits/summary/?${periodQs(range)}`),
    placeholderData: (previous) => previous,
    retry: false,
  })

function invalidateHabits(client: QueryClient) {
  client.invalidateQueries({ queryKey: ['habits-today'] })
  client.invalidateQueries({ queryKey: ['habit-logs'] })
  client.invalidateQueries({ queryKey: ['habits-summary'] })
  client.invalidateQueries({ queryKey: ['today'] })
}

/** Bump today's count straight away so a tap feels instant; the server confirms. */
function bumpToday(client: QueryClient, kind: HabitKind, by: number) {
  client.setQueryData<HabitToday>(['habits-today'], (old) => {
    if (!old) return old
    // R13 §9: caffeine lives in its own block, not in `counts`.
    if (kind === 'caffeine' && old.caffeine) return { ...old, caffeine: { ...old.caffeine, count: Math.max(0, old.caffeine.count + by) } }
    return { ...old, counts: { ...old.counts, [kind]: Math.max(0, (old.counts[kind] ?? 0) + by) } }
  })
}

export function useLogHabit() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: HabitLogBody) => api<HabitLog>('/habits/logs/', { method: 'POST', ...json(body) }),
    onMutate: (body) => {
      // Only today's logs move today's counts.
      if (!body.at || body.at.slice(0, 10) === todayISO()) bumpToday(client, body.kind, body.quantity ?? 1)
    },
    onSettled: () => invalidateHabits(client),
  })
}

export function useDeleteHabitLog() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (log: Pick<HabitLog, 'id' | 'kind' | 'quantity' | 'local_date'>) =>
      api(`/habits/logs/${log.id}/`, { method: 'DELETE' }),
    onMutate: (log) => {
      if (log.local_date === todayISO()) bumpToday(client, log.kind, -log.quantity)
    },
    onSettled: () => invalidateHabits(client),
  })
}

export const useHabitLogs = (kind: HabitKind | null, start: string, end: string, enabled = true) =>
  useQuery({
    queryKey: ['habit-logs', kind, start, end],
    queryFn: () => api<HabitLog[]>(`/habits/logs/?${kind ? `kind=${kind}&` : ''}start=${start}&end=${end}`),
    enabled,
    placeholderData: (previous) => previous,
  })

/** Edit a log (quantity, time, note). */
export function useUpdateHabitLog() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; quantity?: number; at?: string; note?: string }) =>
      api<HabitLog>(`/habits/logs/${id}/`, { method: 'PATCH', ...json(body) }),
    onSettled: () => invalidateHabits(client),
  })
}

/** R9 §B — Settings: delete every 🌙 Private log. */
export function useDeletePrivateLogs() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ deleted?: number } | undefined>('/habits/logs/?kind=private', { method: 'DELETE' }),
    onSettled: () => invalidateHabits(client),
  })
}

/** AI explanation of the habit numbers; cached per day server-side. */
export function useHabitSummaryText(range: PeriodQuery | InsightRange) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<HabitSummaryText | HabitSummary>(`/habits/summary/?${periodQs(range)}${refresh ? '&refresh=1' : ''}`, { method: 'POST' }),
    onSuccess: (data) => {
      const summary = data && 'smoke' in data ? data.summary : data
      if (summary && 'markdown' in summary) {
        client.setQueryData<HabitSummary>(['habits-summary', periodQs(range)], (old) => (old ? { ...old, summary } : old))
      }
      client.invalidateQueries({ queryKey: ['habits-summary', periodQs(range)] })
    },
  })
}

// --- R8 §C / R9 §D: progress --------------------------------------------------------

/** `window=5` or `start=…&end=…[&compare_start=…&compare_end=…]` — mutually exclusive. */
export function progressParams(q: ProgressQuery): string {
  if ('window' in q) return `window=${q.window}`
  const parts = [`start=${q.start}`, `end=${q.end}`]
  if (q.compare_start && q.compare_end) parts.push(`compare_start=${q.compare_start}`, `compare_end=${q.compare_end}`)
  return parts.join('&')
}

export const useProgress = (q: ProgressQuery, enabled = true) =>
  useQuery({
    queryKey: ['progress', progressParams(q)],
    queryFn: () => api<Progress>(`/progress/?${progressParams(q)}&sport=running`),
    placeholderData: (previous) => previous,
    retry: false,
    enabled,
  })

export function useProgressReview(q: ProgressQuery) {
  const client = useQueryClient()
  const params = progressParams(q)
  return useMutation({
    mutationFn: () => api<ProgressReview | Progress>(`/progress/review/?${params}`, { method: 'POST' }),
    onSuccess: (data) => {
      const review = 'metrics' in data ? data.review : data
      if (review) client.setQueryData<Progress>(['progress', params], (old) => (old ? { ...old, review } : old))
    },
  })
}

// --- R8 §D: weather --------------------------------------------------------------------

/** No weather is not an error: 404/503 → null and the UI simply hides the chip. */
export const useWeatherToday = () =>
  useQuery({
    queryKey: ['weather-today'],
    queryFn: async () => {
      try {
        return await api<WeatherToday>('/weather/today/')
      } catch (error) {
        if (error instanceof ApiError && [404, 502, 503, 504].includes(error.status)) return null
        throw error
      }
    },
    staleTime: 15 * 60_000,
    retry: false,
  })

// --- R9 §E: guides ---------------------------------------------------------------------

/** Not deployed yet / failing → null; the guides grid works without "For you". */
export const useGuides = () =>
  useQuery({
    queryKey: ['guides'],
    queryFn: async () => {
      try {
        return await api<GuidesResponse>('/guides/')
      } catch (error) {
        if (error instanceof ApiError && [404, 500, 502, 503, 504].includes(error.status)) return null
        throw error
      }
    },
    staleTime: 10 * 60_000,
    retry: false,
  })

// --- R10 (docs/API_NOTES.md "R10") -------------------------------------------------------

/**
 * Optional R10 reads: not deployed yet / failing upstream → null, so the card hides
 * itself instead of showing an error (the watch may simply not provide the metric).
 */
async function optional<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path)
  } catch (error) {
    if (error instanceof ApiError && [404, 501, 502, 503, 504].includes(error.status)) return null
    throw error
  }
}

const keep = <T,>(previous: T | undefined) => previous

export const healthFitnessQuery = (range: string) =>
  queryOptions({ queryKey: ['health-fitness', periodQs(range)], queryFn: () => optional<HealthFitness>(`/health/fitness/?${periodQs(range)}`), retry: false })
export const useHealthFitness = (range: string) =>
  useQuery({ ...healthFitnessQuery(range), placeholderData: keep })

export const useTrainingStatus = (range?: PeriodQuery) =>
  useQuery({ queryKey: ['training-status', range ? periodQs(range) : ''], queryFn: () => optional<TrainingStatus>(`/health/training-status/${range ? `?${periodQs(range)}` : ''}`), placeholderData: keep, retry: false, staleTime: 5 * 60_000 })

export const healthSleepQuery = (range: string) =>
  queryOptions({ queryKey: ['health-sleep', periodQs(range)], queryFn: () => optional<HealthSleep>(`/health/sleep/?${periodQs(range)}`), retry: false })
export const useHealthSleep = (range: string) =>
  useQuery({ ...healthSleepQuery(range), placeholderData: keep })

export const useHealthForm = (range: string) =>
  useQuery({ queryKey: ['health-form', periodQs(range)], queryFn: () => optional<HealthForm>(`/health/form/?${periodQs(range)}`), placeholderData: keep, retry: false })

export const useRecords = () =>
  useQuery({ queryKey: ['health-records'], queryFn: () => optional<HealthRecords>('/health/records/'), retry: false })

export const useLungRecovery = (enabled = true) =>
  useQuery({ queryKey: ['lung-recovery'], queryFn: () => optional<LungRecovery>('/habits/lung-recovery/'), retry: false, enabled })

export const useReadinessForecast = () =>
  useQuery({ queryKey: ['readiness-forecast'], queryFn: () => optional<ReadinessForecast>('/health/readiness-forecast/'), retry: false, staleTime: 10 * 60_000 })

// Weekly report

/** `week` = any date in the wanted week; omitted = last complete week. 400 (current week) → null. */
export const useWeeklyReport = (week?: string | null, enabled = true) =>
  useQuery({
    queryKey: ['weekly-report', week ?? 'last'],
    queryFn: async () => {
      try {
        return await optional<WeeklyReport>(`/reports/weekly/${week ? `?week=${week}` : ''}`)
      } catch (error) {
        if (error instanceof ApiError && error.status === 400) return null
        throw error
      }
    },
    retry: false,
    enabled,
    staleTime: 10 * 60_000,
  })

export const useWeeklyReports = () =>
  useQuery({ queryKey: ['weekly-reports'], queryFn: () => optional<WeeklyReportListItem[]>('/reports/weekly/list/'), retry: false })

export function useWeeklyReportAi(week: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<NonNullable<WeeklyReport['ai']>>(`/reports/weekly/ai/?week=${week}${refresh ? '&refresh=1' : ''}`, { method: 'POST' }),
    onSuccess: (ai) => {
      client.setQueriesData<WeeklyReport | null>({ queryKey: ['weekly-report'] }, (old) => (old && old.week_start === week ? { ...old, ai } : old))
    },
  })
}

// Compare any two

export const useCompareMetrics = () =>
  useQuery({ queryKey: ['compare-metrics'], queryFn: () => optional<{ metrics: CompareMetric[] }>('/health/compare/metrics/'), retry: false, staleTime: 60 * 60_000 })

export const useCompare = (x: string, y: string, range: string, lag: 0 | 1) =>
  useQuery({
    queryKey: ['compare', x, y, periodQs(range), lag],
    queryFn: () => api<CompareResult>(`/health/compare/?x=${encodeURIComponent(x)}&y=${encodeURIComponent(y)}&${periodQs(range)}&lag=${lag}`),
    enabled: !!x && !!y && x !== y,
    placeholderData: keep,
    retry: false,
  })

// Gear

export const useGear = () => useQuery({ queryKey: ['gear'], queryFn: () => optional<GearResponse>('/gear/'), retry: false })

export type ShoeDraft = { name?: string; brand?: string; retire_km?: number; start_km?: number; is_default?: boolean; in_use_since?: string | null; retired?: boolean }

export function useSaveShoe() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: ShoeDraft & { id?: number }) =>
      id != null
        ? api<Shoe>(`/gear/${id}/`, { method: 'PATCH', ...json(body) })
        : api<Shoe>('/gear/', { method: 'POST', ...json(body) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['gear'] }),
  })
}

export function useDeleteShoe() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/gear/${id}/`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['gear'] }),
  })
}

// Reminders (web push)

export const useReminders = () =>
  useQuery({ queryKey: ['reminders'], queryFn: () => optional<RemindersResponse>('/reminders/'), retry: false })

type ReminderPatch = Record<string, Partial<Pick<Reminder, 'enabled' | 'time'>> & Partial<Omit<Nudge, 'key' | 'label' | 'description'>>> & {
  quiet_hours?: { start?: string; end?: string }
}

export function usePatchReminders() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: ReminderPatch) =>
      api<RemindersResponse>('/reminders/', { method: 'PATCH', ...json(patch) }),
    onMutate: (patch) => {
      client.setQueryData<RemindersResponse | null>(['reminders'], (old) =>
        old ? {
          ...old,
          reminders: old.reminders.map((r) => (patch[r.key] ? { ...r, ...patch[r.key] } : r)),
          nudges: old.nudges?.map((n) => (patch[n.key] ? { ...n, ...patch[n.key] } : n)),
          quiet_hours: patch.quiet_hours && old.quiet_hours ? { ...old.quiet_hours, ...patch.quiet_hours } : old.quiet_hours,
        } : old)
    },
    onSuccess: (data) => client.setQueryData(['reminders'], data),
    onError: () => client.invalidateQueries({ queryKey: ['reminders'] }),
  })
}

export const subscribePush = (sub: PushSubscriptionJSON) =>
  api<{ id: number; created: boolean }>('/reminders/subscribe/', { method: 'POST', ...json({ endpoint: sub.endpoint, keys: sub.keys }) })

export const unsubscribePush = (endpoint: string) =>
  api<{ deleted: number }>('/reminders/unsubscribe/', { method: 'POST', ...json({ endpoint }) })

export const testPush = () => api<{ sent: number; failed: number }>('/reminders/test/', { method: 'POST' })

// Achievements

export const useAchievements = () =>
  useQuery({ queryKey: ['achievements'], queryFn: () => optional<Achievements>('/achievements/'), retry: false, staleTime: 60_000 })

export function useMarkBadgesSeen() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ updated: number }>('/achievements/seen/', { method: 'POST' }),
    onSuccess: () => {
      client.setQueryData<Achievements | null>(['achievements'], (old) =>
        old ? { ...old, unseen: 0, badges: old.badges.map((b) => ({ ...b, new: false })) } : old)
    },
  })
}

export const useBody = (range = '6m') =>
  useQuery({ queryKey: ['health-body', periodQs(range)], queryFn: () => optional<HealthBody>(`/health/body/?${periodQs(range)}`), retry: false })

// --- R11 (docs/API_NOTES.md "R11") ------------------------------------------------------

/** Health → Day. 400 (future / too old) → null, like a day with no data. */
export const healthDayQuery = (date: string) =>
  queryOptions({
    queryKey: ['health-day', date],
    queryFn: async () => {
      try {
        return await optional<HealthDay>(`/health/day/?date=${date}`)
      } catch (error) {
        if (error instanceof ApiError && error.status === 400) return null
        throw error
      }
    },
    retry: false,
  })
export const useHealthDay = (date: string) => useQuery({ ...healthDayQuery(date), placeholderData: keep })

export const useDaySummary = () =>
  useQuery({ queryKey: ['health-day-summary'], queryFn: () => optional<DaySummary>('/health/day/summary/'), retry: false, staleTime: 60_000 })

export const dayTrendsQuery = (range: string) =>
  queryOptions({ queryKey: ['health-day-trends', periodQs(range)], queryFn: () => optional<DayTrends>(`/health/day/trends/?${periodQs(range)}`), retry: false })
export const useDayTrends = (range: string) =>
  useQuery({ ...dayTrendsQuery(range), placeholderData: keep })

export const useActivityRoute = (id: number | null) =>
  useQuery({
    queryKey: ['activity-route', id],
    queryFn: () => optional<ActivityRoute>(`/activities/${id}/route/`),
    enabled: id != null,
    retry: false,
    staleTime: 10 * 60_000,
  })

// Water

export const useWater = (date: string) =>
  useQuery({ queryKey: ['water', date], queryFn: () => optional<WaterDay>(`/diet/water/?date=${date}`), retry: false, placeholderData: keep })

function storeWater(client: QueryClient, day: WaterDay) {
  client.setQueryData(['water', day.date], day)
  client.setQueryData<DietDay>(['diet-day', day.date], (old) => (old ? { ...old, water: day } : old))
}

export function useAddWater() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { ml: number; at?: string }) => api<{ log: WaterLog; day: WaterDay }>('/diet/water/', { method: 'POST', ...json(body) }),
    onSuccess: (r) => storeWater(client, r.day),
  })
}

export function useDeleteWater() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<WaterDay>(`/diet/water/${id}/`, { method: 'DELETE' }),
    onSuccess: (day) => storeWater(client, day),
  })
}

// --- R12 §B (docs/API_NOTES.md "R12"): wake planner, my alarm, watch alarms ---------------

/** `date` = the morning to plan (default tomorrow; today..today+7). */
export const useWakePlan = (date?: string, enabled = true) =>
  useQuery({
    queryKey: ['wake-plan', date ?? 'next'],
    queryFn: async () => {
      try {
        return await optional<WakePlan>(`/health/wake-plan/${date ? `?date=${date}` : ''}`)
      } catch (error) {
        if (error instanceof ApiError && error.status === 400) return null
        throw error
      }
    },
    enabled,
    retry: false,
    staleTime: 5 * 60_000,
  })

export const useMyAlarm = () =>
  useQuery({ queryKey: ['alarm'], queryFn: () => optional<MyAlarm>('/alarm/'), retry: false })

export type AlarmPatch = Partial<Pick<MyAlarm, 'time' | 'days' | 'enabled' | 'push' | 'run_time' | 'bedtime_reminder' | 'bedtime_lead_min'>>

export function usePatchAlarm() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: AlarmPatch) => api<MyAlarm>('/alarm/', { method: 'PATCH', ...json(patch) }),
    onMutate: (patch) => {
      client.setQueryData<MyAlarm | null>(['alarm'], (old) => (old ? { ...old, ...patch } : old))
    },
    onSuccess: (data) => {
      client.setQueryData(['alarm'], data)
      client.invalidateQueries({ queryKey: ['wake-plan'] })
    },
    onError: () => client.invalidateQueries({ queryKey: ['alarm'] }),
  })
}

export const useWatchAlarms = (enabled = true) =>
  useQuery({ queryKey: ['watch-alarms'], queryFn: () => optional<WatchAlarms>('/health/watch-alarms/'), retry: false, enabled, staleTime: 30 * 60_000 })
