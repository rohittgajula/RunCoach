/**
 * Token handling.
 *
 * The access token lives in this module variable and nowhere else — not
 * localStorage (any injected script could read it and exfiltrate a valid token),
 * not a cookie (that would reintroduce CSRF). It dies on page refresh, which is
 * why `refreshAccess()` runs once on load: the refresh token sits in an httpOnly
 * cookie the browser sends but JavaScript cannot read.
 */

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

let accessToken: string | null = null

/** In-flight refresh, shared so five concurrent 401s cause one refresh, not five. */
let refreshInFlight: Promise<string | null> | null = null

export const setAccessToken = (token: string | null) => {
  accessToken = token
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : 'Request failed')
  }

  /** Flattens DRF's {field: [messages]} into something a form can show. */
  fieldErrors(): Record<string, string> {
    if (!this.detail || typeof this.detail !== 'object') return {}
    return Object.fromEntries(
      Object.entries(this.detail as Record<string, unknown>).map(([key, value]) => [
        key,
        Array.isArray(value) ? String(value[0]) : String(value),
      ]),
    )
  }

  get message(): string {
    const errors = this.fieldErrors()
    return errors.detail ?? Object.values(errors)[0] ?? 'Something went wrong.'
  }
}

/**
 * Rotation blacklists the previous refresh token immediately, so two concurrent
 * refreshes are not merely wasteful — the second presents a token the first just
 * revoked and gets a 401, logging the user out. React StrictMode double-invokes
 * effects in development, so this is the normal case, not an edge one.
 */
async function refreshAccess(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${BASE}/auth/refresh/`, {
      method: 'POST',
      credentials: 'include',
    })
      .then(async (response) => {
        if (!response.ok) return null
        const data = await response.json()
        accessToken = data.access
        return data.access as string
      })
      .catch(() => null)
      .finally(() => {
        // Cleared on the next tick, not synchronously: a caller that started while
        // the request was resolving would otherwise begin a second rotation with a
        // cookie the browser has not yet replaced.
        setTimeout(() => {
          refreshInFlight = null
        }, 0)
      })
  }
  return refreshInFlight
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const send = () =>
    fetch(`${BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        // FormData (meal photos) must set its own multipart boundary.
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...init.headers,
      },
    })

  let response = await send()

  // A 15-minute access token expires mid-session constantly. Refresh once and
  // replay rather than bouncing the user to login for a token that is merely stale.
  if (response.status === 401 && !path.startsWith('/auth/refresh')) {
    const token = await refreshAccess()
    if (token) response = await send()
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => response.statusText)
    throw new ApiError(response.status, detail)
  }
  // Mutations and sync-status polls (a background sync finished) trigger; other reads only record.
  const trigger = (init.method ?? 'GET').toUpperCase() !== 'GET' || path.startsWith('/sync/status')
  const header = response.headers.get('X-Data-Version')
  if (response.status === 204) {
    noteDataVersion(header, null, trigger)
    return undefined as T
  }
  const body = (await response.json()) as T
  noteDataVersion(header, body, trigger)
  return body
}

// R18 §B: the server bumps a per-athlete data_version on every change that ripples
// (settings, memory, decisions, illness, edits, syncs). A mutation reply carrying a
// different one than we last saw means "everything derived may have changed".
let dataVersion: unknown
const dvListeners = new Set<() => void>()
export const onDataVersionChange = (fn: () => void) => { dvListeners.add(fn); return () => { dvListeners.delete(fn) } }
function noteDataVersion(header: string | null, body: unknown, trigger: boolean) {
  const v = header ?? (body && typeof body === 'object' && 'data_version' in body ? String((body as { data_version: unknown }).data_version) : null)
  if (v == null || v === 'null' || v === 'undefined') return
  const changed = dataVersion !== undefined && v !== dataVersion
  dataVersion = v
  if (changed && trigger) dvListeners.forEach((l) => l())
}

export const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) })

/**
 * R13 §15: an authenticated file download (the export ZIP is served by the backend with
 * auth, never as a public link). `path` may be an absolute /api/... URL from the server.
 */
export async function apiBlob(path: string): Promise<Blob> {
  const url = /^https?:|^\/api\//.test(path) ? path : `${BASE}${path}`
  const send = () =>
    fetch(url, { credentials: 'include', headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} })
  let response = await send()
  if (response.status === 401) {
    const token = await refreshAccess()
    if (token) response = await send()
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => response.statusText)
    throw new ApiError(response.status, detail)
  }
  return response.blob()
}

/** Called once on load: turns the httpOnly refresh cookie into a live session. */
export async function restoreSession(): Promise<boolean> {
  return (await refreshAccess()) !== null
}

// --- types -------------------------------------------------------------------

export type User = { id: number; username: string; email: string; is_staff?: boolean }

export type SleepNeed = { minutes: number; source: string; garmin_minutes: number | null; label: string }

export type Athlete = {
  id: number
  display_name: string
  timezone: string
  date_of_birth: string | null
  weight_kg: number | null
  resting_hr: number | null
  max_hr: number | null
  easy_pace_min: number
  easy_pace_max: number
  hr_easy_min: number
  hr_easy_max: number
  hr_ceiling: number
  run_cadence_threshold: number
  available_days: Record<string, boolean>
  long_run_day: number
  training_days_per_week: number
  onboarding_complete: boolean
  zones: {
    resting_hr: number
    max_hr: number
    max_source: string
    zones: Array<{ name: string; label: string; low: number; high: number; purpose: string }>
  } | null
  garmin_connected: boolean
  garmin_last_sync: string | null
  // RunCoach additions (SPEC §2)
  sex?: 'male' | 'female' | null
  height_cm?: number | null
  diet_goal?: 'maintain' | 'lose' | 'gain'
  diet_rate_kg_per_week?: number
  threshold_pace_s?: number | null
  // R8 §A — runs per week (null = coach default).
  runs_per_week?: number | null
  runs_per_week_recommended?: number | null
  runs_per_week_effective?: number | null
  // R8 §B — habits.
  smoke_goal?: 'quit' | 'reduce' | 'none'
  smoke_quit_date?: string | null
  smoke_baseline_per_day?: number | null
  cigarette_price?: number | null
  alcohol_goal?: 'reduce' | 'none'
  sugar_goal?: 'reduce' | 'none'
  daily_limits?: Record<string, number> | null
  // R9 §B — shown only as 🌙 Private.
  private_habit_enabled?: boolean
  private_on_today?: boolean
  private_goal?: 'reduce' | 'none'
  // R8 §D — location for weather.
  location_lat?: number | null
  location_lon?: number | null
  location_name?: string
  location_source?: 'runs' | 'city' | 'none'
  location_city?: string
  // R11 §E — trim the first/last 200 m of every run map (default on).
  map_hide_endpoints?: boolean
  // R13 — auto-adjust, strength, caffeine tile, daily pain check, savings goal.
  auto_adjust_plan?: boolean
  strength_per_week?: number
  gym_days?: Record<string, boolean>
  gym_equipment?: string
  strength_per_week_suggested?: number
  caffeine_on_today?: boolean
  pain_daily_check?: boolean
  savings_goal_name?: string
  savings_goal_amount?: number | null
  // R14 — Customise Today (enabled optional cards, in order; null = defaults) and
  // weather swaps applied without asking.
  today_layout?: string[] | null
  weather_auto_apply?: boolean
  // Only on a PATCH that changed strength_per_week.
  strength_reflow?: { created: number; removed: number }
  // Only on a PATCH response: what changing the training days did to the active plan.
  plan_reflow?: PlanReflow | null
  // R18 §B — the athlete's own values win over Garmin's (null = use Garmin's / default).
  sleep_need_minutes?: number | null
  /** Read-only: the effective need used everywhere. */
  sleep_need?: SleepNeed | null
  /** "HH:MM" local, or null. */
  usual_run_time?: string | null
  loop_distance_km?: number | null
  data_version?: number | string
}

export type PlanReflow = {
  moved: number
  dropped: number
  watch_updated: number
  watch_removed: number
  /** R8 §A — sessions rebuilt for a new runs-per-week count, and why some weeks differ. */
  regenerated?: number
  notes?: string[]
}

export type Session = { user: User; athlete: Athlete; access?: string; is_staff?: boolean }

export type RegistrationMode = 'open' | 'invite' | 'closed'


export type ActivityMetrics = {
  run_distance_m: number
  walk_distance_m: number
  run_fraction: number
  run_duration_s: number
  walk_duration_s: number
  run_block_count: number
  longest_run_m: number
  longest_run_s: number
  run_pace_s_per_km: number | null
  walk_pace_s_per_km: number | null
  blended_pace_s_per_km: number | null
  avg_run_cadence_spm: number | null
  avg_run_hr: number | null
  hr_drift_percent: number | null
  custom_load: number | null
  time_in_zone: Record<string, number> | null
}

export type Segment = {
  index: number
  kind: 'run' | 'walk' | 'stop'
  start_offset_s: number
  duration_s: number
  distance_m: number
  avg_pace_s_per_km: number | null
  avg_cadence_spm: number | null
  hr_avg: number | null
  hr_max: number | null
  hr_recovery_60s: number | null
  hr_overshoot_bpm: number | null
}

export type Activity = {
  id: number
  local_date: string
  sport: string
  started_at: string
  total_distance_m: number
  total_timer_s: number
  total_elapsed_s: number
  avg_hr: number | null
  max_hr: number | null
  avg_cadence_spm: number | null
  segmentation_version: number | null
  metrics: ActivityMetrics | null
  segments?: Segment[]
}


export type DailyMetrics = {
  metric_date: string
  sleep_seconds: number | null
  sleep_need_seconds: number | null
  sleep_score: number | null
  deep_sleep_seconds: number | null
  rem_sleep_seconds: number | null
  awake_seconds: number | null
  hrv_overnight_avg: number | null
  hrv_status: string
  training_readiness: number | null
  training_readiness_level: string
  training_status: string
  acute_load: number | null
  chronic_load: number | null
  acwr: number | null
  resting_hr: number | null
  steps: number | null
  stress_avg: number | null
  body_battery_high: number | null
  body_battery_low: number | null
  intensity_minutes: number | null
  spo2_avg: number | null
  respiration_avg: number | null
  vo2max: number | null
}
