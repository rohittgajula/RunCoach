/**
 * R14 contract (docs/API_NOTES.md "R14"): weather report + weather-smart reschedule,
 * calendar feed, self-experiments, long-term goals, heart adaptation and the staff admin.
 * Reads tolerate a missing endpoint (404/5xx → null) so the UI hides quietly on an
 * older server.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from './auth'
import { invalidatePlanData } from './queries'
import type { ISODate, ISODateTime } from './types'

async function optional<T>(path: string): Promise<T | null> {
  try {
    return await api<T>(path)
  } catch (error) {
    if (error instanceof ApiError && [404, 501, 502, 503, 504].includes(error.status)) return null
    throw error
  }
}

// --- §3 weather report --------------------------------------------------------------

export type RunVerdict = 'good' | 'ok' | 'poor' | 'bad'
export type DayVerdict = 'good' | 'caution' | 'bad'

export type WeatherReportHour = {
  time: string
  temp: number | null
  feels_like: number | null
  humidity: number | null
  dew_point: number | null
  precip_prob: number | null
  wind: number | null
  uv: number | null
  weather_code: number | null
  condition: string | null
  aqi: number | null
  pm25: number | null
  run: RunVerdict | null
  best: boolean
}

export type WeatherReportDay = {
  date: ISODate
  temp_min: number | null
  temp_max: number | null
  feels_like_max: number | null
  precip_prob_max: number | null
  precip_mm: number | null
  weather_code: number | null
  condition: string | null
  uv_max: number | null
  aqi_max: number | null
  sunrise: string | null
  sunset: string | null
  run_verdict: DayVerdict | null
  reasons: string[]
}

export type RunVsWeather = {
  date: ISODate
  workout_id: number
  title: string
  kind: string
  duration_s: number
  verdict: DayVerdict | null
  reasons: string[]
  best_window: { start: string; end: string; reason: string } | null
  suggestion_id: number | null
}

export type DayBrief = {
  date: ISODate
  best_feels_like: number | null
  precip_prob_max: number | null
  aqi_max: number | null
  condition: string | null
  verdict: DayVerdict
}

export type WeatherSuggestion = {
  id: number
  workout_id: number | null
  workout_title: string
  workout_kind: string
  duration_s: number
  from_date: ISODate
  to_date: ISODate
  action: 'move' | 'swap'
  swap_with: { workout_id: number; title: string; kind: string } | null
  text: string
  reason: string
  reasons: Array<{ key: 'heat' | 'storm' | 'rain' | 'air' | (string & {}); text: string }>
  from_weather: DayBrief | null
  to_weather: DayBrief | null
  status: 'pending' | 'applied' | 'dismissed' | 'expired'
  auto_applied: boolean
  created_at: ISODateTime
  decided_at: ISODateTime | null
}

export type WeatherReport = {
  available: boolean
  reason: null | 'no_location' | 'unavailable' | (string & {})
  location_name: string | null
  source: 'runs' | 'city' | 'none'
  generated_at: ISODateTime
  now: null | {
    time: string
    temp: number | null
    feels_like: number | null
    humidity: number | null
    dew_point: number | null
    wind: number | null
    uv: number | null
    weather_code: number | null
    condition: string | null
    aqi: number | null
    pm25: number | null
    aqi_level: 'good' | 'moderate' | 'sensitive' | 'unhealthy' | 'very_unhealthy' | 'hazardous' | null
    aqi_meaning: string | null
    uv_level: 'low' | 'moderate' | 'high' | 'very_high' | 'extreme' | null
  }
  hourly: WeatherReportHour[]
  best_windows: Array<{ date: ISODate; start: string; end: string; reason: string; feels_like: number | null; aqi: number | null }>
  daily: WeatherReportDay[]
  sun: { sunrise: string | null; sunset: string | null } | null
  heat: 'cool' | 'warm' | 'hot' | 'very_hot' | null
  pace_slowdown_pct: number
  advisories: Array<{ level: 'info' | 'caution' | 'warning'; text: string }>
  hydration: { before_ml: number | string; during_ml_per_h: number | string | null; after_note: string; electrolytes: boolean } | null
  food: string[]
  daily_water_bonus_ml: number
  runs: RunVsWeather[]
  suggestions: WeatherSuggestion[]
}

export const useWeatherReport = () =>
  useQuery({ queryKey: ['weather-report'], queryFn: () => optional<WeatherReport>('/weather/report/'), retry: false, staleTime: 10 * 60_000 })

export const useWeatherSuggestions = () =>
  useQuery({
    queryKey: ['weather-suggestions'],
    queryFn: () => optional<{ auto_apply: boolean; suggestions: WeatherSuggestion[] }>('/plan/weather-suggestions/'),
    retry: false,
    staleTime: 5 * 60_000,
  })

export function useDecideSuggestion() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'apply' | 'dismiss' }) =>
      api<WeatherSuggestion>(`/plan/weather-suggestions/${id}/${action}/`, { method: 'POST' }),
    onSettled: (_d, _e, vars) => {
      client.invalidateQueries({ queryKey: ['weather-suggestions'] })
      client.invalidateQueries({ queryKey: ['weather-report'] })
      if (vars.action === 'apply') {
        invalidatePlanData(client)
        for (const key of ['today', 'briefing', 'week', 'calendar-feed']) client.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}

// --- §5 calendar feed ---------------------------------------------------------------

export type CalendarFeed = {
  enabled: boolean
  url: string | null
  webcal_url: string | null
  google_url: string | null
  path: string | null
  created_at: ISODateTime | null
  last_fetched_at: ISODateTime | null
}

export const useCalendarFeed = () =>
  useQuery({ queryKey: ['calendar-feed'], queryFn: () => optional<CalendarFeed>('/calendar-feed/'), retry: false })

export function useCalendarFeedActions() {
  const client = useQueryClient()
  const create = useMutation({
    mutationFn: () => api<CalendarFeed>('/calendar-feed/', { method: 'POST' }),
    onSuccess: (feed) => client.setQueryData(['calendar-feed'], feed),
  })
  const revoke = useMutation({
    mutationFn: () => api('/calendar-feed/', { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['calendar-feed'] }),
  })
  return { create, revoke }
}

// --- §7 experiments -----------------------------------------------------------------

export type ExperimentKind = 'no_alcohol' | 'no_late_caffeine' | 'no_sugar' | 'smoke_free' | 'bed_by' | 'steps' | 'custom'
export type ExperimentRule = {
  habit?: 'alcohol' | 'caffeine' | 'sugar' | 'smoke' | 'private'
  max_per_day?: number
  after?: string
  bedtime?: string
  min_steps?: number
}
export type Experiment = {
  id: number
  kind: ExperimentKind | (string & {})
  title: string
  start: ISODate
  end: ISODate
  days: number
  rule: ExperimentRule
  status: 'scheduled' | 'active' | 'completed' | 'stopped'
  decision: 'keep' | 'stop' | null
  created_at: ISODateTime
  ended_at: ISODateTime | null
  progress: { day: number; days: number; pct: number } | null
  adherence: {
    days_counted: number
    days_kept: number
    pct: number | null
    today: boolean | null
    series: Array<{ date: ISODate; kept: boolean | null; value: number | null }>
  } | null
  chip: string
}
export type ExperimentMetric = {
  key: 'hrv' | 'rhr' | 'sleep_score' | 'stress' | 'easy_hr' | 'mood' | 'energy' | (string & {})
  label: string
  unit: string
  before: number | null
  during: number | null
  diff: number | null
  n_before: number
  n_during: number
  higher_is_better: boolean
  enough_data: boolean
  direction: 'better' | 'worse' | 'no_clear_difference' | null
  sentence: string
}
export type ExperimentResult = {
  final: boolean
  baseline: { start: ISODate; end: ISODate }
  during: { start: ISODate; end: ISODate }
  adherence_pct: number | null
  metrics: ExperimentMetric[]
  summary: string
  caveat: string
  share: { title: string; lines: string[] } | null
}
export type ExperimentTemplate = {
  kind: ExperimentKind
  title: string
  description: string
  rule: ExperimentRule
  default_days: number
  source: 'habits' | 'caffeine' | 'sleep' | 'steps' | (string & {})
}

export const useActiveExperiment = () =>
  useQuery({ queryKey: ['experiment-active'], queryFn: () => optional<{ experiment: Experiment | null }>('/experiments/active/'), retry: false, staleTime: 5 * 60_000 })

// --- §8 goals -----------------------------------------------------------------------

export type GoalKind = 'race_time' | 'distance' | 'weight' | 'smoke_free_days' | 'vo2max' | 'resting_hr' | 'weekly_km' | 'custom'
export type Goal = {
  id: number
  kind: GoalKind | (string & {})
  title: string
  unit: string
  target: number
  target_date: ISODate | null
  start_value: number | null
  start_date: ISODate
  distance_km: number | null
  direction: 'up' | 'down'
  current: number | null
  current_as_of: ISODate | null
  current_source: string | null
  progress_pct: number | null
  status: 'active' | 'achieved' | 'abandoned'
  achieved_on: ISODate | null
  milestones: Array<{ pct: number; value: number; reached_on: ISODate | null }>
  projection: { date: ISODate | null; method: 'trend' | null; label: string; on_track: boolean | null; note: string } | null
  series: Array<{ date: ISODate; value: number }>
  display: { target: string; current: string | null; start: string | null } | null
  chip: string
  created_at: ISODateTime
}
export type GoalBody = {
  kind?: GoalKind
  target?: number
  target_date?: ISODate | null
  title?: string
  distance_km?: number
  unit?: string
  start_value?: number
  status?: 'active' | 'abandoned'
}

export const useGoalChip = () =>
  useQuery({ queryKey: ['goal-chip'], queryFn: () => optional<{ goal: Goal | null; text: string | null }>('/goals/chip/'), retry: false, staleTime: 10 * 60_000 })

// --- §9 heart adaptation ------------------------------------------------------------

export type HeartRun = {
  activity_id: number
  date: ISODate
  started_at: ISODateTime
  distance_km: number | null
  run_s: number | null
  steady_s: number | null
  hr_at_ref_pace: number | null
  hr_at_ref_pace_adj: number | null
  pace_at_ref_hr: number | null
  efficiency: number | null
  efficiency_adj: number | null
  decoupling_pct: number | null
  hr_recovery_bpm: number | null
  hr_recovery_end_bpm: number | null
  settle_s: number | null
  duration_under_cap_s: number
  feels_like_c: number | null
  hot: boolean | null
  elev_gain_per_km: number | null
  hilly: boolean
  flags: string[]
}
export type HeartTrendPoint = {
  date: ISODate
  activity_id: number
  hr_at_ref_pace: number | null
  pace_at_ref_hr: number | null
  efficiency: number | null
  decoupling_pct: number | null
  duration_under_cap_s: number | null
}
export type HeartSnapshot = {
  date: ISODate
  runs: number
  duration_under_cap_s: number | null
  hr_at_ref_pace: number | null
  pace_at_ref_hr: number | null
  efficiency: number | null
}
export type HeartKeyNumber = {
  key: 'duration_under_cap' | 'hr_at_ref_pace' | 'pace_at_ref_hr' | 'decoupling' | (string & {})
  label: string
  value: number | null
  unit: string
  display: string | null
  change: number | null
  better: boolean | null
  info: string
}
export type HeartResponse = {
  range: string
  start: ISODate
  end: ISODate
  ref_hr: number
  ref_hr_band: number
  ref_pace_s_per_km: number
  ref_pace_band_s: number
  hot_threshold_c: number
  runs: HeartRun[]
  trend: HeartTrendPoint[]
  trend_cool: HeartTrendPoint[]
  since_day1: null | { first: HeartSnapshot; latest: HeartSnapshot; sentences: string[] }
  heat: {
    hot_runs: number
    cool_runs: number
    unknown_runs: number
    hot_vs_cool: null | { metric: string; hot_avg: number; cool_avg: number; diff: number; n_hot: number; n_cool: number }
    adaptation: null | { early_hot_avg: number; recent_hot_avg: number; diff: number; n_early: number; n_recent: number }
    sentence: string | null
  } | null
  headline: string
  sentences: string[]
  key_numbers: HeartKeyNumber[]
  weather_pending: boolean
  caveat: string
}
