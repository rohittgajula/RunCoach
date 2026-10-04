import {
  useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient,
} from '@tanstack/react-query'
import { ApiError, api, json } from './auth'
import { addDays, todayISO } from './format'
import type {
  ActivityCard, CalendarResponse, DietDay, DietTrend, FitnessResponse, GarminStatus,
  Meal, MealEstimate, MemoryFact, Message, MetricEntriesResponse, MetricEntry, MetricKind,
  Plan, PlanSummary, ProfileSummary, Race, Range, SendResult, Thread, ThreadListItem,
  Workout, AttachmentRef, SyncResult, CoachReview, InsightRange, Insights, MonthResponse,
  WorkoutActual, Compliance, TodayCheckin, PendingCheckin, CheckinBody, CheckinEntry,
  GarminSendResult,
} from './types'

export const errorText = (error: unknown, fallback = 'Something went wrong.'): string =>
  error instanceof ApiError ? error.message : fallback

/** Everything that depends on the plan. Accepting/declining/moving touches all of it. */
export function invalidatePlanData(client: QueryClient) {
  for (const key of ['calendar', 'calendar-month', 'calendar-day', 'plan-active', 'plans', 'plan', 'profile-summary', 'diet-day', 'workout']) {
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

export const useActivePlan = () =>
  useQuery({
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

export function useCalendar() {
  const today = todayISO()
  return useInfiniteQuery({
    queryKey: ['calendar'],
    initialPageParam: { start: addDays(today, -SPAN), end: addDays(today, SPAN) } as Window,
    queryFn: ({ pageParam }) =>
      api<CalendarResponse>(`/calendar/?start=${pageParam.start}&end=${pageParam.end}`),
    getNextPageParam: (_last, _all, param) => ({ start: addDays(param.end, 1), end: addDays(param.end, SPAN) }),
    getPreviousPageParam: (_first, _all, param) => ({ start: addDays(param.start, -SPAN), end: addDays(param.start, -1) }),
    // Each page is ~29 days; keep enough to scroll a season either way.
    maxPages: 14,
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
    mutationFn: () => api<SyncResult>('/garmin/sync/', { method: 'POST', ...json({ limit: 20 }) }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['garmin-status'] })
      client.invalidateQueries({ queryKey: ['calendar'] })
      client.invalidateQueries({ queryKey: ['profile-summary'] })
      client.invalidateQueries({ queryKey: ['diet-day'] })
      client.invalidateQueries({ queryKey: ['calendar-month'] })
      client.invalidateQueries({ queryKey: ['insights'] })
      client.invalidateQueries({ queryKey: ['today'] })
      client.invalidateQueries({ queryKey: ['checkins-pending'] })
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

export const useThreads = () =>
  useQuery({ queryKey: ['threads'], queryFn: () => api<ThreadListItem[]>('/chat/threads/') })

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

export const useDietDay = (date: string) =>
  useQuery({
    queryKey: ['diet-day', date],
    queryFn: () => api<DietDay>(`/diet/day/?date=${date}`),
    placeholderData: (previous) => previous,
  })

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

export const useInsights = (range: InsightRange) =>
  useQuery({
    queryKey: ['insights', range],
    queryFn: () => api<Insights>(`/insights/?range=${range}`),
    placeholderData: (previous) => previous,
  })

/** Cached per day server-side; `refresh` rewrites today's overview. */
export function useInsightsSummary(range: InsightRange) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<NonNullable<Insights['summary']>>(`/insights/summary/?range=${range}${refresh ? '&refresh=1' : ''}`, { method: 'POST' }),
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
