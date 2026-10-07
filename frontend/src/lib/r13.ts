/**
 * R13 contract (docs/API_NOTES.md "R13"): types + react-query hooks for auto-adjust,
 * race plan, injury watch, strength, briefing, post-run review, cravings + savings,
 * caffeine, mood, monthly reports and data export. Every read tolerates a missing
 * endpoint (404/5xx → null) so the UI degrades quietly on an older server.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, api, json } from './auth'
import { invalidatePlanData, periodQs } from './queries'
import type { ISODate, ISODateTime, ResponsePeriod } from './types'

async function optional<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path)
  } catch (error) {
    if (error instanceof ApiError && [404, 501, 502, 503, 504].includes(error.status)) return null
    throw error
  }
}

const keep = <T,>(previous: T | undefined) => previous

// --- §1 auto-adjust -----------------------------------------------------------------

export type AdjustmentSignalKey =
  | 'rpe' | 'hr_high' | 'hr_drift' | 'incomplete' | 'readiness' | 'sleep_debt' | 'alcohol' | 'pain' | 'injury_risk' | 'easy_streak'
  | (string & {})

export type AdjustmentSide = { title: string; kind: string; duration_s: number | null; date: ISODate }

export type Adjustment = {
  id: number
  workout_id: number | null
  workout_date: ISODate
  workout_title: string
  activity_id: number | null
  trigger: 'run' | 'checkin' | 'pain' | (string & {})
  action: 'shorten' | 'easier' | 'run_walk' | 'rest' | 'swap' | 'extend' | (string & {})
  reason: string
  /** "Adjusted: shortened to 20 min — your HR ran 8 bpm high yesterday" */
  chip: string
  signals: Array<{ key: AdjustmentSignalKey; label: string }>
  before: AdjustmentSide
  after: AdjustmentSide
  group: string | null
  status: 'applied' | 'undone'
  undoable: boolean
  created_at: ISODateTime
  undone_at: ISODateTime | null
}

export const useAdjustments = (enabled = true) =>
  useQuery({
    queryKey: ['adjustments'],
    queryFn: () => optional<{ enabled: boolean; adjustments: Adjustment[] }>('/adjustments/?limit=20'),
    enabled,
    retry: false,
    staleTime: 60_000,
  })

export function useUndoAdjustment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<Adjustment>(`/adjustments/${id}/undo/`, { method: 'POST' }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['adjustments'] })
      invalidatePlanData(client)
      for (const key of ['today', 'briefing', 'calendar', 'workout']) client.invalidateQueries({ queryKey: [key] })
    },
  })
}

// --- §2 race plan -------------------------------------------------------------------

export type RaceStrategy = 'even' | 'negative'
export type RacePlan = {
  race: { id: number; name: string; date: ISODate; distance_km: number; goal_time_s?: number | null; start_time?: string | null }
  strategy: RaceStrategy
  available: boolean
  reason: null | 'no_target' | (string & {})
  start_time: string
  start_time_source: 'race' | 'default'
  days_to_race: number
  target: null | {
    time_s: number
    pace_s_per_km: number
    source: 'goal' | 'prediction' | 'garmin' | (string & {})
    goal_time_s: number | null
    predicted_time_s: number | null
    note: string | null
  }
  splits: Array<{ km: number; split_s: number; pace_s_per_km: number; elapsed_s: number }>
  fueling: {
    duration_s: number | null
    carbs_g_per_h: number
    fluid_ml_per_h: number
    electrolytes: boolean
    items: Array<{ at_s: number; at_km: number | null; what: string; amount: string }>
    notes: string[]
  }
  weather: null | {
    date: ISODate; hour: string; temp_c: number | null; feels_like_c: number | null; humidity: number | null
    dew_point: number | null; precip_prob: number | null; wind_kmh: number | null
    heat: 'cool' | 'warm' | 'hot' | 'very_hot' | (string & {}); pace_slowdown_pct: number; advice: string[]
  }
  warmup: Array<{ label: string; duration_s: number; detail: string }>
  taper: {
    starts_on: ISODate
    in_taper: boolean
    items: Array<{ key: string; label: string; detail: string; due_on: ISODate | null; status: 'ok' | 'warn' | 'todo' | 'info' | (string & {}) }>
  }
  morning: Array<{ time: string; label: string; detail: string }>
}

export const useRacePlan = (id: number | null, strategy: RaceStrategy = 'even') =>
  useQuery({
    queryKey: ['race-plan', id, strategy],
    queryFn: () => optional<RacePlan>(`/races/${id}/plan/?strategy=${strategy}`),
    enabled: id != null,
    retry: false,
    placeholderData: keep,
  })

// --- §3 injury watch ---------------------------------------------------------------

export type InjuryRisk = 'low' | 'moderate' | 'high'
export type PainLocation = 'foot' | 'ankle' | 'shin' | 'calf' | 'knee' | 'hamstring' | 'quad' | 'hip' | 'lower_back'
export type PainSideApi = 'left' | 'right' | 'both' | 'center'
export type Pain = {
  id: number
  date: ISODate
  location: PainLocation
  side: PainSideApi
  severity: 1 | 2 | 3
  activity_id: number | null
  note: string
  created_at: ISODateTime
}
export type InjuryFlag = {
  kind: 'ramp' | 'long_run_share' | 'cadence_drop' | 'gct_balance' | 'shoe' | 'pain' | (string & {})
  level: 'watch' | 'high'
  text: string
  since: ISODate | null
  value: number | null
}
export type InjuryWatch = {
  date: ISODate
  risk: InjuryRisk
  flags: InjuryFlag[]
  pains: Pain[]
  guidance: string[]
  note: string
}

export const useInjury = () =>
  useQuery({ queryKey: ['injury'], queryFn: () => optional<InjuryWatch>('/health/injury/'), retry: false, staleTime: 5 * 60_000 })

export const usePains = (days = 30, enabled = true) =>
  useQuery({ queryKey: ['pains', days], queryFn: () => optional<Pain[]>(`/health/pain/?days=${days}`), retry: false, enabled })

export type PainBody = { location: PainLocation; side: PainSideApi; severity: 1 | 2 | 3; date?: ISODate; activity_id?: number | null; note?: string }

function invalidatePain(client: QueryClient) {
  for (const key of ['injury', 'pains', 'today', 'briefing', 'adjustments', 'calendar']) client.invalidateQueries({ queryKey: [key] })
}

/** One POST per spot (the server upserts same date+location+side). */
export function useReportPains() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (pains: PainBody[]) => {
      const out: Pain[] = []
      for (const p of pains) out.push(await api<Pain>('/health/pain/', { method: 'POST', ...json(p) }))
      return out
    },
    onSuccess: () => invalidatePain(client),
  })
}

export function useDeletePain() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/health/pain/${id}/`, { method: 'DELETE' }),
    onSuccess: () => invalidatePain(client),
  })
}

// --- §4 strength ---------------------------------------------------------------------

export type StrengthExercise = {
  key: 'calf' | 'bridge' | 'split' | 'plank' | 'side' | 'clam' | 'askip' | 'hipflexor' | (string & {})
  name: string
  sets: number
  reps: number | null
  seconds: number | null
  per_side: boolean
  rest_s: number
  cue: string
}
export type Strength = {
  id: number
  date: ISODate
  title: string
  duration_s: number
  level: number
  exercises: StrengthExercise[]
  status: 'planned' | 'completed' | 'skipped'
  completed_activity_id: number | null
  auto_completed: boolean
  after_run: boolean
  garmin_status: 'none' | 'synced' | 'changed'
  garmin_workout_id: number | null
  can_send_to_watch: boolean
}
export type StrengthList = { per_week: number; suggested: number; can_send_to_watch: boolean; sessions: Strength[] }

export const useStrength = (start?: string, end?: string, enabled = true) =>
  useQuery({
    queryKey: ['strength', start ?? '', end ?? ''],
    queryFn: () => optional<StrengthList>(`/strength/${start && end ? `?start=${start}&end=${end}` : ''}`),
    retry: false,
    enabled,
  })

function invalidateStrength(client: QueryClient) {
  for (const key of ['strength', 'calendar', 'calendar-month', 'calendar-day', 'briefing']) client.invalidateQueries({ queryKey: [key] })
}

export function usePatchStrength() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; status?: Strength['status']; date?: ISODate }) =>
      api<Strength>(`/strength/${id}/`, { method: 'PATCH', ...json(body) }),
    onSuccess: () => invalidateStrength(client),
  })
}

export function useStrengthToWatch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, remove = false }: { id: number; remove?: boolean }) =>
      api<{ queued: boolean }>(`/strength/${id}/garmin/`, { method: remove ? 'DELETE' : 'POST' }),
    onSuccess: () => invalidateStrength(client),
  })
}

// --- §6 briefing ---------------------------------------------------------------------

export type Briefing = {
  date: ISODate
  ready: boolean
  built_at: ISODateTime | null
  dismissed: boolean
  wake_time: string | null
  greeting: string
  readiness: { score: number | null; label: string | null; source: 'garmin' | null | (string & {}) } | null
  checkin: { verdict: string; headline: string } | null
  session: {
    workout: { id: number; title: string; kind: string; duration_s: number } | null
    adjustment: Adjustment | null
    strength: { id: number; title: string } | null
  } | null
  weather: null | {
    best_window: { start: string; end: string; reason: string } | null
    feels_like_max: number | null
    heat: string | null
    hydration: { before_ml: number; during_ml_per_h: number; after_note: string; electrolytes: boolean } | null
  }
  fuel: null | { kcal: number; carbs_g: number; protein_g: number; water_ml: number }
  focus: { key: string; text: string } | null
  notes: Array<{ kind: 'injury' | 'habit' | 'sleep' | 'mood' | 'review' | (string & {}); text: string }>
  ai: { status: 'none' | 'ready'; text: string; generated_at: ISODateTime | null } | null
}

export const useBriefing = () =>
  useQuery({ queryKey: ['briefing'], queryFn: () => optional<Briefing>('/briefing/today/'), retry: false, staleTime: 10 * 60_000 })

export function useDismissBriefing() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ dismissed: boolean }>('/briefing/today/dismiss/', { method: 'POST' }),
    onMutate: () => {
      client.setQueryData<Briefing | null>(['briefing'], (b) => (b ? { ...b, dismissed: true } : b))
    },
  })
}

export function useBriefingAi() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<{ status: 'none' | 'ready'; text: string; generated_at: ISODateTime | null }>(`/briefing/today/ai/${refresh ? '?refresh=1' : ''}`, { method: 'POST' }),
    onSuccess: (ai) => client.setQueryData<Briefing | null>(['briefing'], (b) => (b ? { ...b, ai } : b)),
  })
}

// --- §7 post-run review ----------------------------------------------------------------

export type RunReviewMetric = {
  key: 'pace' | 'hr_at_pace' | 'hr_drift' | 'cadence' | 'run_fraction' | (string & {})
  label: string
  unit: string
  this_run: number | null
  typical: number | null
  delta: number | null
  better: boolean | null
}
export type RunReview = {
  activity_id: number
  date: ISODate
  available: boolean
  reason: null | 'not_a_run' | 'no_metrics' | (string & {})
  kind: string | null
  bucket: 'lt2' | '2to5' | '5to8' | '8plus' | null
  compared_with: number
  metrics: RunReviewMetric[]
  went_well: string[]
  to_improve: string[]
  next_time: string[]
  ai: { status: 'none' | 'ready'; markdown: string; generated_at: ISODateTime | null } | null
  created_at: ISODateTime | null
}

export const useRunReview = (activityId: number | null) =>
  useQuery({
    queryKey: ['run-review', activityId],
    queryFn: () => optional<RunReview>(`/activities/${activityId}/review/`),
    enabled: activityId != null,
    retry: false,
  })

export const useRecentReview = () =>
  useQuery({
    queryKey: ['run-review', 'recent'],
    queryFn: async () => (await optional<{ review: RunReview | null }>('/reviews/recent/'))?.review ?? null,
    retry: false,
    staleTime: 5 * 60_000,
  })

export function useRunReviewAi(activityId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<{ status: 'none' | 'ready'; markdown: string; generated_at: ISODateTime | null }>(`/activities/${activityId}/review/ai/${refresh ? '?refresh=1' : ''}`, { method: 'POST' }),
    onSuccess: (ai) => {
      client.setQueryData<RunReview | null>(['run-review', activityId], (r) => (r ? { ...r, ai } : r))
      client.setQueryData<RunReview | null>(['run-review', 'recent'], (r) => (r && r.activity_id === activityId ? { ...r, ai } : r))
    },
  })
}

// --- §8 cravings + savings -------------------------------------------------------------

export const CRAVING_TRIGGERS = [
  { key: 'coffee', label: 'Coffee' },
  { key: 'alcohol', label: 'Alcohol' },
  { key: 'stress', label: 'Stress' },
  { key: 'after_meal', label: 'After a meal' },
  { key: 'boredom', label: 'Boredom' },
  { key: 'social', label: 'With friends' },
  { key: 'work_break', label: 'Work break' },
  { key: 'morning', label: 'Morning' },
  { key: 'other', label: 'Other' },
] as const
export type CravingTrigger = (typeof CRAVING_TRIGGERS)[number]['key']
export const triggerLabel = (k: string) => CRAVING_TRIGGERS.find((t) => t.key === k)?.label ?? k

export type Craving = {
  id: number
  at: ISODateTime
  local_date: ISODate
  intensity: number
  trigger: CravingTrigger
  place: string
  mood: number | null
  smoked: boolean
  cigarette_log_id: number | null
  note: string
  created_at: ISODateTime
}
export type CravingBody = { intensity: number; trigger: CravingTrigger; at?: string; place?: string; mood?: number | null; smoked?: boolean; note?: string }

export type Savings = {
  name: string
  amount: number
  saved: number
  remaining: number
  pct: number
  reached: boolean
  per_day: number | null
  eta: ISODate | null
}
export type CravingSummary = {
  range: string
  start: ISODate
  end: ISODate
  period?: ResponsePeriod | null
  total: number
  resisted: number
  resisted_pct: number | null
  avg_intensity: number | null
  by_trigger: Array<{ trigger: string; label: string; count: number; resisted: number }>
  by_hour: Array<{ hour: number; count: number }>
  top_places: Array<{ place: string; count: number }>
  peak_hours: Array<{ hour: number; count: number }>
  trend: { this_period: number; previous_period: number; change_pct: number | null; direction: 'down' | 'up' | 'flat' | null } | null
  savings: Savings | null
}

function invalidateQuit(client: QueryClient) {
  for (const key of ['cravings', 'craving-summary', 'habits-today', 'habits-summary', 'habit-logs', 'achievements']) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useLogCraving() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: CravingBody) => api<Craving>('/habits/cravings/', { method: 'POST', ...json(body) }),
    onSuccess: () => invalidateQuit(client),
  })
}

export function usePatchCraving() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<CravingBody> & { id: number }) =>
      api<Craving>(`/habits/cravings/${id}/`, { method: 'PATCH', ...json(body) }),
    onSuccess: () => invalidateQuit(client),
  })
}

export const useCravingSummary = (range: string = '4w', enabled = true) =>
  useQuery({
    queryKey: ['craving-summary', periodQs(range)],
    queryFn: () => optional<CravingSummary>(`/habits/cravings/summary/?${periodQs(range)}`),
    retry: false,
    placeholderData: keep,
    enabled,
  })

// --- §9 caffeine ---------------------------------------------------------------------------

export type CaffeineSubtype = 'coffee' | 'tea' | 'energy' | 'other'
export type CaffeineReport = {
  range: string
  start: ISODate
  end: ISODate
  period?: ResponsePeriod | null
  total: number
  per_day_avg: number | null
  by_type: Record<CaffeineSubtype, number>
  late_cutoff: string
  late_days: number
  series: Array<{ date: ISODate; count: number; late: boolean }>
  impact: Array<{
    metric: 'sleep_score' | 'deep_sleep_min' | 'awake_min' | (string & {})
    label: string
    unit: string
    late_avg: number | null
    other_avg: number | null
    diff: number | null
    n_late: number
    n_other: number
    direction: 'better' | 'worse' | 'no_clear_difference'
    enough_data: boolean
    sentence: string
  }>
  caveat: string
}

export const useCaffeine = (range: string, enabled = true) =>
  useQuery({
    queryKey: ['caffeine', periodQs(range)],
    queryFn: () => optional<CaffeineReport>(`/habits/caffeine/?${periodQs(range)}`),
    retry: false,
    placeholderData: keep,
    enabled,
  })

// --- §10 mood & energy ---------------------------------------------------------------------

export type Mood = { date: ISODate; mood: number; energy: number; note: string; updated_at: ISODateTime }

export const useMoodToday = () =>
  useQuery({ queryKey: ['mood', 'today'], queryFn: () => optional<{ date: ISODate; entry: Mood | null }>('/mood/today/'), retry: false })

export function useSaveMood() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { mood: number; energy: number; note?: string; date?: ISODate }) => api<Mood>('/mood/', { method: 'POST', ...json(body) }),
    onSuccess: (saved) => {
      client.setQueryData(['mood', 'today'], { date: saved.date, entry: saved })
      client.invalidateQueries({ queryKey: ['briefing'] })
      client.invalidateQueries({ queryKey: ['today'] })
    },
  })
}

// --- §11 monthly report -----------------------------------------------------------------------

export type Change = { start: number | null; end: number | null; change: number | null }
export type MonthlyReport = {
  id: number
  month: string
  start: ISODate
  end: ISODate
  generated_at: ISODateTime
  runs: { count: number; km: number; run_km: number; time_s: number; longest_km: number; previous_count: number; previous_km: number; planned: number; planned_done: number }
  prs: Array<{ key: string; label: string; display: string; date: ISODate | null }>
  fitness: { vo2max: Change; fitness_age: Change } | null
  wellness: Array<{ metric: string; label: string; unit: string; this_month: number | null; previous_month: number | null; delta: number | null; better: boolean | null }>
  habits: Array<{ habit: string; label: string; this_month: number; previous_month: number; delta: number; better: boolean | null }>
  smoke_free_days: number | null
  mood: { mood_avg: number | null; energy_avg: number | null; days: number; previous_mood_avg: number | null; previous_energy_avg: number | null } | null
  weight: { start: number; end: number; change: number } | null
  injury: { flags: number; pain_days: number } | null
  went_well: string[]
  to_improve: string[]
  goal: string
  ai: { status: 'none' | 'ready'; markdown: string; generated_at: ISODateTime | null } | null
}
export type MonthlyReportListItem = { id: number; month: string; runs_done: number; km: number; generated_at: ISODateTime }

export const useMonthlyReport = (month: string | null) =>
  useQuery({
    queryKey: ['monthly-report', month ?? 'latest'],
    queryFn: () => optional<MonthlyReport>(`/reports/monthly/${month ? `?month=${month}` : ''}`),
    retry: false,
  })

export const useMonthlyReports = () =>
  useQuery({ queryKey: ['monthly-reports'], queryFn: () => optional<MonthlyReportListItem[]>('/reports/monthly/list/'), retry: false })

export function useMonthlyReportAi(month: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (refresh: boolean) =>
      api<{ status: 'none' | 'ready'; markdown: string; generated_at: ISODateTime | null }>(`/reports/monthly/ai/?month=${month}${refresh ? '&refresh=1' : ''}`, { method: 'POST' }),
    onSuccess: (ai) => {
      for (const key of [month, 'latest']) {
        client.setQueryData<MonthlyReport | null>(['monthly-report', key], (r) => (r && r.month === month ? { ...r, ai } : r))
      }
    },
  })
}

// --- §15 data export ---------------------------------------------------------------------------

export type ExportJob = {
  id: number
  status: 'pending' | 'running' | 'ready' | 'failed' | 'expired' | 'downloaded'
  created_at: ISODateTime
  finished_at: ISODateTime | null
  size_bytes: number | null
  expires_at: ISODateTime | null
  download_url: string | null
  error: string
}

export const exportBusy = (e: ExportJob | null | undefined) => e?.status === 'pending' || e?.status === 'running'

/** `undefined` while loading, `null` when the endpoint is missing, else {export}. Polls while building. */
export const useExportStatus = () =>
  useQuery({
    queryKey: ['export'],
    queryFn: () => optional<{ export: ExportJob | null }>('/export/latest/'),
    retry: false,
    refetchInterval: (q) => (exportBusy(q.state.data?.export) ? 3000 : false),
  })

export function useRequestExport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<ExportJob>('/export/', { method: 'POST' }),
    onSuccess: (job) => client.setQueryData(['export'], { export: job }),
  })
}
