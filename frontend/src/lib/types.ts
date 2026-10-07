/**
 * The API contract — SPEC.md §5. Field names must match the backend exactly.
 * Existing endpoints (auth, athlete, garmin, races, activities) keep their types in
 * auth.ts / here where they were not typed before.
 */

export type Range = '3m' | '6m' | '1y'
export type ISODate = string // YYYY-MM-DD, athlete-local
export type ISODateTime = string

// --- planning ------------------------------------------------------------------

export type Intensity = 'walk' | 'easy' | 'moderate' | 'hard'
export type StepKind = 'warmup' | 'run' | 'walk' | 'stride' | 'recovery' | 'cooldown' | 'interval'

export type Step = {
  kind: StepKind
  duration_s: number
  intensity: Intensity
  label: string
  pace_min_s: number | null
  pace_max_s: number | null
  hr_min: number | null
  hr_max: number | null
}

export type Fueling = {
  before: string
  during: string
  after: string
  carbs_g_during_per_h: number | null
}

export type PhaseKind = 'base' | 'build' | 'peak' | 'taper' | 'recovery' | 'race'

export type Phase = {
  id: number
  order: number
  name: string
  kind: PhaseKind
  start: ISODate
  end: ISODate
  description: string
}

export type Race = {
  id: number
  name: string
  date: ISODate
  distance_km: number
  is_target: boolean
  notes: string
}

export type PlanStatus = 'proposed' | 'active' | 'archived' | 'declined'

export type PlanSummary = {
  id: number
  name: string
  goal: string
  status: PlanStatus
  race: Race | null
  phase_count: number
  start: ISODate
  end: ISODate
  current_phase_id: number | null
  phases: Phase[]
}

export type PlanWeek = {
  start: ISODate
  end: ISODate
  planned_minutes: number
  planned_load: number
  phase_id: number | null
}

export type Plan = PlanSummary & {
  summary: Record<string, unknown>
  weeks: PlanWeek[]
}

export type WorkoutStatus = 'planned' | 'completed' | 'skipped'

export type Workout = {
  id: number
  date: ISODate
  title: string
  kind: string
  phase: { id: number; name: string; kind: PhaseKind } | null
  duration_s: number
  load: number
  steps: Step[]
  description: string
  purpose: string
  target_zone: string
  fueling: Fueling
  status: WorkoutStatus
  completed_activity_id: number | null
  /** R6 §3 — present once a run is linked. */
  actual?: WorkoutActual | null
  compliance?: Compliance | null
  review?: CoachReview | null
  /** R7 §1 — set when the morning check-in rewrote today's steps. */
  adjusted_by?: 'checkin' | string | null
  original_steps?: Step[] | null
  /** R7 §3 — easy/long/run-walk only. */
  guard?: WorkoutGuard | null
  /** R7 §3 — Garmin upload state (null until sent). */
  garmin_workout_id?: string | number | null
  garmin_synced_at?: ISODateTime | null
  /** none | synced | changed — whether the watch copy matches the steps now. */
  garmin_status?: 'none' | 'synced' | 'changed'
}

// --- R6 §3: actual vs planned ------------------------------------------------------

export type Zone = 'Z1' | 'Z2' | 'Z3' | 'Z4' | 'Z5'

export type WorkoutActual = {
  activity_id: number
  duration_s: number
  distance_m: number
  // Null when the activity has no derived metrics (no FIT file yet).
  run_distance_m: number | null
  walk_distance_m: number | null
  run_fraction: number | null
  longest_run_s: number | null
  avg_hr: number | null
  max_hr: number | null
  avg_cadence_spm: number | null
  avg_pace_s_per_km: number | null
  time_in_zone: Partial<Record<Zone, number>> | null
  steps: Step[] | null
  // §6 extras (nullable).
  max_cadence_spm?: number | null
  avg_stride_length_m?: number | null
  avg_vertical_oscillation_cm?: number | null
  avg_ground_contact_ms?: number | null
  avg_respiration?: number | null
  training_effect_aerobic?: number | null
  training_effect_anaerobic?: number | null
  /** R7 §3 — run-block time over the easy-day HR cap. */
  time_above_cap_s?: number | null
  time_above_cap_pct?: number | null
}

export type ComplianceStatus = 'hit' | 'close' | 'missed'

export type ComplianceCheck = {
  key: string
  label: string
  status: ComplianceStatus
  planned: string | number | null
  actual: string | number | null
  note: string
}

export type Compliance = { score: number; checks: ComplianceCheck[] }

export type CoachReview = {
  status: 'none' | 'ready'
  summary_md: string
  went_well: string[]
  to_improve: string[]
  generated_at?: ISODateTime | null
}

export type ActivityCard = {
  id: number
  name: string
  sport: string
  device: string
  start: ISODateTime
  duration_s: number
  distance_m: number
  load: number
  run_distance_m: number
  walk_distance_m: number
  run_fraction: number
  longest_run_s: number
  steps: Step[] | null
  journalled: boolean
  reviewed_thread_id: number | null
  /** R6 §2 — a run on a day with no planned run. */
  unplanned?: boolean
}

export type CalItem =
  | { type: 'workout'; workout: Workout }
  | { type: 'activity'; activity: ActivityCard }

export type CalDay = {
  date: ISODate
  items: CalItem[]
  rest: 'Rest' | 'Recovery day' | null
}

export type CalWeek = {
  start: ISODate
  end: ISODate
  planned_s: number
  planned_load: number
  actual_s: number
  actual_load: number
}

export type CalendarResponse = {
  today: ISODate
  days: CalDay[]
  weeks: CalWeek[]
}

// --- R6 §4: month calendar ---------------------------------------------------------

export type MonthDayStatus = 'done' | 'missed' | 'partial' | 'planned' | 'rest' | 'extra' | 'today'

export type MonthDay = {
  date: ISODate
  planned: { kind: string; title: string; duration_s: number; id?: number } | null
  status: MonthDayStatus | null
  activities: Array<{ id: number; sport: string; duration_s: number; distance_m: number }>
}

export type MonthResponse = {
  month: string // YYYY-MM
  today: ISODate
  days: MonthDay[]
  totals: {
    planned_s: number; actual_s: number; runs_done: number; runs_planned: number; runs_missed: number
    runs_extra?: number
  }
}

// --- profile / metrics -----------------------------------------------------------

export type FitnessStatus =
  | 'detraining'
  | 'fresh'
  | 'maintaining'
  | 'gaining'
  | 'overtraining'
  | 'insufficient_data'

export type ProfileSummary = {
  athlete: {
    display_name: string
    threshold_pace_s: number | null
    weight_kg: number | null
    easy_pace_min: number | null
    easy_pace_max: number | null
  }
  wellness: { hrv_ms: number | null; resting_hr: number | null; sleep_s: number | null; date: ISODate } | null
  fitness: { value: number | null; fatigue: number | null; form: number | null; status: FitnessStatus; spark: number[] }
  status_spark: number[]
  active_plan: PlanSummary | null
  memory_count: number
}

export type FitnessPoint = { date: ISODate; fitness: number; fatigue: number; form: number }

export type FitnessResponse = {
  series: FitnessPoint[]
  current: { fitness: number | null; fatigue: number | null; form: number | null; status: FitnessStatus }
}

export type MetricKind = 'weight' | 'threshold_pace' | 'resting_hr' | 'max_hr'
export type MetricSource = 'manual' | 'garmin' | 'estimated'

export type MetricEntry = { id: number; value: number; recorded_at: ISODateTime; source: MetricSource }

export type MetricEntriesResponse = {
  kind: MetricKind
  current: MetricEntry | null
  entries: MetricEntry[]
}

// --- chat ----------------------------------------------------------------------

export type ThreadListItem = { id: number; title: string; updated_at: ISODateTime }
export type Thread = { id: number; title: string; created_at?: ISODateTime; updated_at: ISODateTime }

export type Attachment =
  | { type: 'workout'; workout: Workout }
  | { type: 'activity'; activity: ActivityCard }
  | { type: 'plan_proposal'; plan: PlanSummary }
  | { type: 'meal'; meal: Meal }

export type AttachmentRef = { type: 'workout' | 'activity' | 'plan_proposal' | 'meal' | 'image'; id: number }

export type MessageStatus = 'pending' | 'done' | 'error'

export type Message = {
  id: number
  role: 'user' | 'assistant' | 'tool'
  content: string
  attachments: Attachment[]
  status: MessageStatus
  created_at: ISODateTime
}

export type SendResult = { user: Message; assistant: Message }

export type MemoryFact = { id: number; text: string; source: 'chat' | 'manual'; created_at: ISODateTime }

// --- diet ----------------------------------------------------------------------

export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack'
export type MealSource = 'ai_photo' | 'ai_text' | 'manual'
export type Confidence = 'low' | 'medium' | 'high'

export type MealItem = {
  name: string
  quantity: string
  kcal: number
  carbs_g: number
  protein_g: number
  fat_g: number
}

export type Meal = {
  id: number
  eaten_at: ISODateTime
  local_date: ISODate
  meal_type: MealType
  description: string
  photo_url: string | null
  items: MealItem[]
  kcal: number
  carbs_g: number
  protein_g: number
  fat_g: number
  source: MealSource
  ai_confidence: Confidence | null
}

export type Macros = { kcal: number; carbs_g: number; protein_g: number; fat_g: number }

export type DietDay = {
  date: ISODate
  targets: Macros & {
    water_ml: number
    rationale: string
    /** R8 §D — included in water_ml when the forecast is warm. */
    water_bonus_ml?: number | null
    water_note?: string | null
  }
  /** R8 §D — hot-day food tips from the forecast (empty on cool days / no location). */
  weather_tips?: string[]
  eaten: Macros
  burn: { bmr: number; non_exercise: number; exercise: number; exercise_source: 'garmin' | 'planned' | 'none' }
  meals: Meal[]
  fueling: Array<Fueling & { workout_id: number; title: string }>
  missing_profile: string[]
}

export type MealEstimate = Macros & {
  description: string
  items: MealItem[]
  confidence: Confidence | null
}

export type DietTrend = {
  series: Array<{ date: ISODate; intake_kcal: number | null; target_kcal: number; weight_kg: number | null }>
  summary: {
    avg_balance_kcal: number | null
    predicted_kg_per_week: number | null
    actual_kg_per_week: number | null
    logged_days_last_7: number
  }
}

// --- garmin (existing endpoints) -------------------------------------------------

export type GarminStatus = { connected: boolean; name: string; error: string; last_sync: string | null }
export type SyncResult = { imported: number; skipped: number; failed: number; errors: string[] }

// --- R6 §5: insights ------------------------------------------------------------------

export type InsightRange = '4w' | '12w' | '6m'

/** Series items carry `date` plus one value field whose name varies (ms, s, value…). */
export type SeriesPoint = { date: ISODate } & Record<string, number | string | null>

export type Insights = {
  readiness: { score: number | null; label: string; drivers: string[]; source: 'garmin' | 'computed' } | null
  hrv: {
    last_night_ms: number | null
    weekly_avg_ms: number | null
    baseline_low: number | null
    baseline_high: number | null
    status: 'balanced' | 'unbalanced' | 'low' | 'poor' | null
    series: Array<{ date: ISODate; ms: number | null }>
  } | null
  sleep: { avg_s: number | null; avg_score: number | null; series: Array<{ date: ISODate; s: number | null; score: number | null }> } | null
  resting_hr: { current: number | null; trend_bpm_per_week: number | null; series: SeriesPoint[] } | null
  body_battery: { avg: number | null; series: SeriesPoint[] } | null
  stress: { avg: number | null; series: SeriesPoint[] } | null
  respiration: { avg_rpm: number | null; sleep_avg_rpm: number | null; series: SeriesPoint[] } | null
  vo2max: { value: number | null; series: SeriesPoint[] } | null
  race_predictions: { '5k_s': number | null; '10k_s': number | null; half_s: number | null; marathon_s?: number | null } | null
  running: {
    runs: number
    run_km: number
    run_fraction_trend: SeriesPoint[]
    longest_run_trend: SeriesPoint[]
    easy_pace_trend: SeriesPoint[]
    /** `trend` is a slope (spm per week), not a series. */
    cadence: { avg: number | null; trend: number | null; target: { low: number; high: number } | null; note: string }
    hr_drift_avg: number | null
    pace_cv_avg: number | null
    form: { ground_contact_ms: number | null; vertical_oscillation_cm: number | null; stride_length_m: number | null } | null
  } | null
  load: { fitness: number | null; fatigue: number | null; form: number | null; status: string; acwr: number | null } | null
  focus: Array<{ key?: string; title: string; why: string; how: string }>
  summary: { status: 'none' | 'ready'; markdown: string; generated_at?: ISODateTime | null } | null
}

// --- R7: morning check-in, post-run check-in, easy-day guard -------------------------

export type Verdict = 'go' | 'easy' | 'swap' | 'rest' | 'no_plan'
export type SignalKey = 'sleep' | 'hrv' | 'rhr' | 'body_battery' | 'readiness' | 'pain' | 'illness' | 'load' | 'stress' | 'alcohol' | 'heat' | 'air'
export type SignalStatus = 'good' | 'watch' | 'bad'

export type SignalReason = {
  signal: SignalKey | string
  status: SignalStatus
  label: string
  value: string | number | boolean | null
  baseline: string | number | null
}

/** What the verdict turns today's workout into — not saved until "Use this". */
export type AdjustedWorkout = Partial<Workout> & { title: string; steps: Step[]; duration_s: number }

export type TodayCheckin = {
  date: ISODate
  verdict: Verdict
  headline: string
  reasons: SignalReason[]
  signals_missing: string[]
  workout: Workout | null
  adjusted: AdjustedWorkout | null
  applied: boolean
  explanation: { status: 'none' | 'ready'; text: string } | null
  /** Recovery note / movement suggestion (no_plan), else null. */
  note?: string | null
}

export type WorkoutGuard = {
  hr_max: number | null
  pace_min_s: number | null
  pace_max_s: number | null
  cadence_target: number | null
}

export type Legs = 'fresh' | 'ok' | 'heavy' | 'sore'
export type Breathing = 'easy' | 'ok' | 'hard'

export type CheckinBody = {
  rpe: number
  legs: Legs
  breathing: Breathing
  pain: { where: string; level: number } | null
  note: string
}

/** The JournalEntry the check-in creates. Structured fields may sit in `extracted`. */
export type CheckinEntry = {
  id: number
  rpe: number | null
  pain_reported: boolean
  legs?: Legs | null
  breathing?: Breathing | null
  pain?: CheckinBody['pain']
  note?: string
  text?: string
  /** `{checkin, skipped, rpe, legs, breathing, pain, note}` or `{skipped: true, reason}`. */
  extracted?: Partial<CheckinBody> & { skipped?: boolean; reason?: string } & Record<string, unknown>
  created_at?: ISODateTime
}

export type PendingCheckin = { activity: ActivityCard; workout_id: number | null }

export type GarminSendResult = {
  workout_id: number
  date?: ISODate
  title?: string
  status: 'uploaded' | 'updated' | 'unchanged' | 'removed' | 'skipped' | 'error' | string
  detail?: string
  garmin_workout_id?: string | number | null
  synced_at?: ISODateTime | null
}

// --- R8 §B: habits (smoking, alcohol, sugar) ----------------------------------------

export type HabitKind = 'smoke' | 'alcohol' | 'sugar'

export type HabitLog = {
  id: number
  kind: HabitKind
  at: ISODateTime
  local_date: ISODate
  quantity: number
  note: string
}

export type HabitToday = {
  date: ISODate
  counts: Record<HabitKind, number>
  last_at: Partial<Record<HabitKind, ISODateTime | null>>
}

export type HabitCountPoint = { date: ISODate; count: number }

export type HabitImpact = {
  habit: HabitKind
  metric: string
  label: string
  with_avg: number | null
  without_avg: number | null
  diff: number | null
  diff_pct: number | null
  n_with: number
  n_without: number
  direction: 'worse' | 'better' | 'no_clear_difference'
  enough_data: boolean
  /** Optional: unit for the metric ("ms", "bpm"); dose rows may carry a dose label. */
  unit?: string
  dose?: string
}

export type HabitMilestone = { label: string; reached: boolean; at: ISODateTime | ISODate | null }

export type HabitSummaryText = { status: 'none' | 'ready'; markdown: string; generated_at?: ISODateTime | null }

export type HabitSummary = {
  range: InsightRange
  smoke: {
    series: HabitCountPoint[]
    total: number
    per_day_avg: number | null
    trend_per_week: number | null
    streak: { current_days: number; best_days: number }
    since_quit: { days: number; cigarettes_avoided: number | null; money_saved: number | null } | null
    milestones: HabitMilestone[]
  }
  alcohol: { series: HabitCountPoint[]; total: number; per_week_avg: number | null; drink_days: number }
  sugar: { series: HabitCountPoint[]; total: number; per_day_avg: number | null }
  impact: HabitImpact[]
  weekly: Array<{
    week_start: ISODate
    cigarettes: number
    drinks: number
    sugar: number
    hrv_avg: number | null
    rhr_avg: number | null
    sleep_score_avg: number | null
    easy_pace_s_per_km: number | null
    efficiency: number | null
  }>
  summary: HabitSummaryText | null
}

export type HabitLogBody = { kind: HabitKind; quantity?: number; at?: ISODateTime; note?: string }

// --- R8 §C: progress comparison -------------------------------------------------------

export type ProgressWindow = 1 | 5 | 10 | 20

export type ProgressMetric = {
  key: string
  label: string
  current: number | null
  previous: number | null
  delta: number | null
  delta_pct: number | null
  better: boolean | null
  unit: string
}

export type ProgressBucket = {
  bucket: string
  runs?: number
  label: string
  current_n?: number
  previous_n?: number
  metrics: ProgressMetric[]
}

/** One best as the API sends it, keyed by name in `bests`. */
export type ProgressBestRaw = { value: number | null; date: ISODate | null; activity_id?: number | null; new: boolean } | null

export type ProgressBest = {
  key: string
  label: string
  value: number | null
  unit: string
  date: ISODate | null
  is_new: boolean
  activity_id?: number | null
}

export type ProgressPoint = {
  date: ISODate
  run_km: number | null
  pace: number | null
  avg_hr: number | null
  efficiency: number | null
  cadence: number | null
  total_km?: number | null
  bucket?: string | null
  activity_id?: number
}

export type ProgressFocus = { key?: string; kind?: 'improve' | 'check' | string; title: string; why?: string; how?: string }

export type ProgressReview = { status?: 'none' | 'ready'; went_well: string[]; improve: string[]; check: string[]; markdown: string; generated_at?: ISODateTime | null }

export type Progress = {
  window: ProgressWindow
  sport?: string
  current_n?: number
  previous_n?: number
  metrics: ProgressMetric[]
  runs?: number
  distance_buckets: ProgressBucket[]
  /** fastest_1k_s · longest_run_km · longest_continuous_s · lowest_easy_hr */
  bests: Record<string, ProgressBestRaw>
  series: ProgressPoint[]
  focus: ProgressFocus[]
  review?: ProgressReview | null
}

// --- R8 §D: weather -------------------------------------------------------------------

export type WeatherHour = {
  time: ISODateTime
  temp: number | null
  feels_like: number | null
  humidity?: number | null
  dew_point?: number | null
  precip_prob?: number | null
  wind?: number | null
  uv?: number | null
  aqi?: number | null
}

export type WeatherAdvisory = { level: 'info' | 'caution' | 'warning' | 'bad' | string; text: string }

export type WeatherToday = {
  /** false with a `reason` (no_location, fetch_failed…) — then `now` is null. */
  available?: boolean
  reason?: string | null
  heat?: string | null
  pace_slowdown_pct?: number
  location_name: string | null
  source: 'runs' | 'city' | 'none'
  now: {
    temp: number | null
    feels_like: number | null
    humidity: number | null
    dew_point: number | null
    aqi: number | null
    pm25: number | null
    condition: string
  } | null
  hourly: WeatherHour[]
  best_window: { start: string; end: string; reason: string } | null
  advisories: WeatherAdvisory[]
  hydration: { before_ml: number | string; during_ml_per_h: number | string | null; after_note: string; electrolytes: boolean } | null
  food: string[]
  daily_water_bonus_ml: number
}
