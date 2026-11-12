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
  /** R13 §2 */
  goal_time_s?: number | null
  start_time?: string | null
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
  /** Set only on a practice plan: the unbroken block it is building toward. */
  milestone?: {
    label: string | null
    seconds: number | null
    distance_m: number | null
    index: number | null
    total: number | null
  } | null
  kind?: 'practice' | 'race' | 'other'
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

export type WorkoutStatus = 'planned' | 'completed' | 'skipped' | 'paused'

export type Workout = {
  id: number
  date: ISODate
  title: string
  kind: string
  phase: { id: number; name: string; kind: PhaseKind } | null
  duration_s: number
  load: number
  steps: Step[]
  /** R18 §B: estimated km (+ loops when the athlete set a loop distance). */
  distance_estimate?: { km: number; loops: number | null; loop_km: number | null } | null
  description: string
  purpose: string
  target_zone: string
  fueling: Fueling
  status: WorkoutStatus
  /** R17 §10: illness id that paused it / return-to-run block it belongs to. */
  paused_by_illness?: number | null
  illness_return?: number | null
  completed_activity_id: number | null
  /** R6 §3 — present once a run is linked. */
  actual?: WorkoutActual | null
  compliance?: Compliance | null
  review?: CoachReview | null
  /** R7 §1 — set when the morning check-in rewrote today's steps. */
  adjusted_by?: 'checkin' | 'auto' | 'kept' | string | null
  /** R13 §1 — the applied auto-adjustment, if any. */
  auto_adjustment?: import('./r13').Adjustment | null
  original_steps?: Step[] | null
  /** R7 §3 — easy/long/run-walk only. */
  guard?: WorkoutGuard | null
  /** R7 §3 — Garmin upload state (null until sent). */
  garmin_workout_id?: string | number | null
  garmin_synced_at?: ISODateTime | null
  /** none | synced | changed — whether the watch copy matches the steps now. */
  garmin_status?: 'none' | 'synced' | 'changed'
  /** R16 §A — the athlete's own edits (app or chat). */
  edited_by?: 'user' | null
  edited_at?: ISODateTime | null
  edited_via?: 'app' | 'chat' | null
  notes?: string
  can_edit?: boolean
  can_undo_edit?: boolean
  planned?: { title: string; kind: string; duration_s: number; run_s: number } | null
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
  | { type: 'strength'; strength: import('./r13').Strength }

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
  // Sent by the month endpoint since R13 §4 and simply never declared here, so
  // the grid could not show a gym day even though it was being told about one.
  strength?: { id: number; title?: string; duration_s?: number } | null
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
  /** R16 §B — workouts a tool changed in this turn ([] when nothing changed). */
  plan_changed?: import('./r16').PlanChange[]
  /** R18 §C — settings a tool changed in this turn. */
  profile_changed?: ProfileChange[]
  /** R16/R18 — the coach is waiting for a Yes/No (workout, week or profile variant). */
  needs_confirmation?: { field?: string; summary?: string } | null
}
export type ProfileChange = { field: string; label: string; before_display?: string | null; after_display?: string | null; summary: string }

export type SendResult = { user: Message; assistant: Message; plan_changed?: import('./r16').PlanChange[]; profile_changed?: ProfileChange[] }

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
  /** R11 §D */
  water?: WaterDay | null
}

export type WaterLog = { id: number; at: string; local_date: ISODate; ml: number }
export type WaterDay = {
  date: ISODate; target_ml: number; bonus_ml: number; drunk_ml: number; remaining_ml: number
  pct: number; quick_add: number[]; logs: WaterLog[]
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

/** R12 §A: every ranged Health body carries the exact period it used. */
export type ResponsePeriod = {
  start: ISODate
  end: ISODate
  compare_start: ISODate | null
  compare_end: ISODate | null
  days?: number
  freq: 'day' | 'week' | 'month'
}

export type InsightRange = '4w' | '12w' | '6m'

/** Series items carry `date` plus one value field whose name varies (ms, s, value…). */
export type SeriesPoint = { date: ISODate } & Record<string, number | string | null>

export type Insights = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  readiness: { score: number | null; label: string; drivers: string[]; source: 'garmin' | 'computed'; date?: ISODate | null } | null
  /** R16 §C */
  as_of?: ISODateTime
  freshness?: import('./r16').Freshness | null
  hrv: {
    last_night_ms: number | null
    last_night_date?: ISODate | null
    weekly_avg_ms: number | null
    baseline_low: number | null
    baseline_high: number | null
    status: 'balanced' | 'unbalanced' | 'low' | 'poor' | null
    series: Array<{ date: ISODate; ms: number | null }>
  } | null
  sleep: { avg_s: number | null; avg_score: number | null; series: Array<{ date: ISODate; s: number | null; score: number | null }> } | null
  resting_hr: { current: number | null; trend_bpm_per_week: number | null; series: SeriesPoint[]; current_date?: ISODate | null } | null
  body_battery: { avg: number | null; series: SeriesPoint[]; date?: ISODate | null } | null
  stress: { avg: number | null; series: SeriesPoint[]; date?: ISODate | null } | null
  respiration: { avg_rpm: number | null; sleep_avg_rpm: number | null; series: SeriesPoint[] } | null
  vo2max: { value: number | null; series: SeriesPoint[]; date?: ISODate | null } | null
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
  /** R16 §C — the day the value is from. */
  date?: ISODate | null
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
  /** R13 §3 / §10 */
  injury?: { risk: import('./r13').InjuryRisk; flags: import('./r13').InjuryFlag[] } | null
  mood?: import('./r13').Mood | null
  /** R16 §C */
  as_of?: ISODateTime
  freshness?: import('./r16').Freshness | null
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

/** R9 §B — `private` is shown only as 🌙 Private. */
export type HabitKind = 'smoke' | 'alcohol' | 'sugar' | 'private' | 'caffeine'

export type HabitLog = {
  id: number
  kind: HabitKind
  at: ISODateTime
  local_date: ISODate
  quantity: number
  note: string
  /** R13 §9 — caffeine only. */
  subtype?: 'coffee' | 'tea' | 'energy' | 'other' | null
}

export type HabitToday = {
  date: ISODate
  /** `private` is omitted entirely while the private habit is disabled. */
  counts: Partial<Record<HabitKind, number>>
  last_at: Partial<Record<HabitKind, ISODateTime | null>>
  /** R13 §9 */
  caffeine?: { count: number; last_at: ISODateTime | null; on_today: boolean }
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
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
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
  /** R9 §B — present only while the private habit is enabled. */
  private?: { series: HabitCountPoint[]; total: number; per_day_avg: number | null } | null
  summary: HabitSummaryText | null
  /** R9 §C — habit health report. */
  report?: HabitReport | null
}

// --- R9 §C: habit health report ------------------------------------------------------

export type HabitStatus = 'improving' | 'worsening' | 'steady' | 'not_enough_data'
export type Tone = 'good' | 'bad' | 'neutral'

export type HabitFinding = { tone: Tone; text: string; kind?: string }

export type HabitReportGarmin = {
  metric: string
  label: string
  unit: string
  now: number | null
  before: number | null
  delta: number | null
  better: boolean | null
}

export type HabitReportHabit = {
  habit: HabitKind
  status: HabitStatus
  headline: string
  amount?: { now_per_day: number | null; before_per_day: number | null; change_pct: number | null; now_per_week?: number | null; before_per_week?: number | null } | null
  findings: HabitFinding[]
}

export type HabitReport = {
  overall: { status: HabitStatus; headline: string } | null
  garmin: HabitReportGarmin[]
  habits: HabitReportHabit[]
}

export type HabitLogBody = { kind: HabitKind; quantity?: number; at?: ISODateTime; note?: string; subtype?: 'coffee' | 'tea' | 'energy' | 'other' }

// --- R8 §C: progress comparison -------------------------------------------------------

export type ProgressWindow = 1 | 5 | 10 | 20

/** R9 §D — either the last-N window or a date range (optionally with a compare range). */
export type ProgressQuery =
  | { window: ProgressWindow }
  | { start: ISODate; end: ISODate; compare_start?: ISODate; compare_end?: ISODate }

export type ProgressPeriod = {
  mode: 'window' | 'dates'
  start: ISODate | null
  end: ISODate | null
  compare_start: ISODate | null
  compare_end: ISODate | null
  runs_current: number
  runs_previous: number
}

export type ProgressHighlight = { tone: Tone; text: string }

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
  window: ProgressWindow | null
  /** R9 §D */
  period?: ProgressPeriod | null
  highlights?: ProgressHighlight[]
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

// --- R9 §E: guides ----------------------------------------------------------------------

export type GuideKey = 'form' | 'breathing' | 'strength' | 'fueling' | 'warmup'

export type GuideForYou = { key: GuideKey; reason: string; priority?: number }

/** Inputs the rules used; every field optional — the UI falls back when missing. */
export type GuidesContext = {
  window_days?: number
  runs?: number
  cadence_avg?: number | null
  /** Suggested metronome: cadence + 5 % (server-rounded). */
  metronome_bpm?: number | null
  hr_drift_runs?: number
  run_fraction_pct?: number | null
  smoking?: boolean
  feels_like_max?: number | null
  longest_upcoming_run_min?: number | null
} & Record<string, unknown>

export type GuidesResponse = { for_you: GuideForYou[]; context: GuidesContext }

// --- R10 (docs/API_NOTES.md "R10") ---------------------------------------------------
// Every field the watch may not provide is nullable; the UI hides what is missing.

export type HealthRange = '7d' | '4w' | '3m' | '6m' | '1y'
export type ValuePoint = { date: ISODate; value: number }
export type RacePred = { '5k_s': number | null; '10k_s': number | null; half_s: number | null; marathon_s: number | null }

export type AthleteZones = {
  resting_hr?: number | null
  max_hr?: number | null
  max_source?: string
  zones: Array<{ name: string; label: string; low: number; high: number; purpose: string }>
  source?: 'heart_rate_reserve' | 'lactate_threshold'
  lt_hr?: number | null
  lt_date?: ISODate | null
  updated_at?: ISODateTime | null
  capped?: boolean
}

export type HealthFitness = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  range: string
  start: ISODate
  end: ISODate
  vo2max?: { current: number | null; change: number | null; series: ValuePoint[] } | null
  fitness_age?: { current: number | null; chronological_age: number | null; achievable: number | null; change: number | null; series: ValuePoint[] } | null
  endurance_score?: { current: number | null; level: string | null; change: number | null; series: ValuePoint[] } | null
  race_predictions?: {
    current: RacePred | null
    previous: RacePred | null
    as_of: ISODate | null
    previous_as_of: ISODate | null
    series: Array<{ date: ISODate } & Partial<RacePred>>
  } | null
  lactate_threshold?: {
    hr: number | null
    pace_s_per_km: number | null
    date: ISODate
    source: 'garmin'
    zones_updated: boolean
    zones_updated_at: ISODateTime | null
    series: Array<{ date: ISODate; hr: number | null; pace_s_per_km: number | null }>
  } | null
  zones?: AthleteZones | null
}

export type LoadFocusItem = {
  key: 'low_aerobic' | 'high_aerobic' | 'anaerobic' | string
  label: string
  value: number
  target_min: number | null
  target_max: number | null
  state: 'below' | 'in_range' | 'above' | null
}

export type TrainingStatus = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  date: ISODate | null
  status: string | null
  status_key: string | null
  acute_load: number | null
  chronic_load: number | null
  acwr: number | null
  load_focus: { date: ISODate; feedback: string | null; period_days: number; items: LoadFocusItem[] } | null
  history: Array<{ date: ISODate; status_key: string | null; acute_load: number | null; chronic_load: number | null }>
}

export type SleepNight = {
  date: ISODate
  sleep_s: number | null
  need_s: number | null
  score: number | null
  deep_s: number | null
  light_s: number | null
  rem_s: number | null
  awake_s: number | null
  bedtime: string | null
  wake_time: string | null
  restless_moments: number | null
  spo2_avg: number | null
  spo2_low: number | null
  breathing_rate: number | null
}

export type SleepAvg = {
  sleep_s: number | null
  need_s: number | null
  score: number | null
  deep_s: number | null
  rem_s: number | null
  spo2_avg: number | null
  breathing_rate: number | null
  restless_moments: number | null
  bedtime: string | null
  wake_time: string | null
}

export type HealthSleep = {
  /** R18: the effective sleep need (override > memory > Garmin > 8 h). */
  need?: { minutes: number; source: string; garmin_minutes?: number | null; label?: string } | null
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  range: string
  start: ISODate
  end: ISODate
  nights: SleepNight[]
  averages: SleepAvg | null
  previous: SleepAvg | null
  regularity: { bedtime_sd_min: number | null; previous_bedtime_sd_min: number | null; n: number; better: boolean | null } | null
  debt: { need_s: number | null; debt_s: number | null; short_nights: number; nights: number; short_by_s: number | null } | null
  sleep_vs_runs: {
    short_h: number
    long_h: number
    short: { easy_hr: number | null; n: number }
    long: { easy_hr: number | null; n: number }
    diff_bpm: number | null
    enough_data: boolean
    sentence: string | null
  } | null
  /** R12: one point per bucket (= per night at freq=day), mean values. */
  series?: Array<{ date: ISODate; n?: number; sleep_s: number | null; need_s: number | null; score: number | null; bedtime_h?: number | null; wake_h?: number | null }>
  tonight: { need_s: number | null; wake_time: string | null; bedtime: string | null } | null
}

export type FormMetric = {
  key: 'cadence' | 'ground_contact' | 'vertical_oscillation' | 'stride_length' | string
  label: string
  unit: string
  current: number | null
  previous: number | null
  change: number | null
  better: boolean | null
  trend_per_week: number | null
  n: number
}

export type HealthForm = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  range: string
  start: ISODate
  end: ISODate
  has_dynamics: boolean
  runs: Array<{
    activity_id: number
    date: ISODate
    cadence_spm: number | null
    ground_contact_ms: number | null
    vertical_oscillation_cm: number | null
    stride_length_m: number | null
    run_km: number
    run_pace_s_per_km: number | null
  }>
  metrics: FormMetric[]
}

export type PersonalRecord = {
  key: string
  label: string
  source: 'garmin' | 'computed'
  unit: 's' | 'm'
  value: number
  display: string
  date: ISODate | null
  activity_id: number | null
  garmin_activity_id: number | null
  is_new: boolean
}

export type HealthRecords = { records: PersonalRecord[]; new_count: number; synced_on: ISODate | null }

export type Shoe = {
  id: number
  name: string
  brand: string
  source: 'garmin' | 'local'
  is_default: boolean
  retired: boolean
  retire_km: number
  start_km: number
  distance_km: number
  activities: number
  in_use_since: ISODate | null
  last_used: ISODate | null
  remaining_km: number
  replace_soon: boolean
  replace_due: boolean
  garmin_uuid: string | null
  created_at: ISODateTime
}

export type GearResponse = { shoes: Shoe[]; default_retire_km: number }

export type LungMetric = {
  key: 'sleep_breathing_rate' | 'spo2' | 'resting_hr' | 'easy_hr' | string
  label: string
  unit: string
  before: number | null
  before_n: number
  now: number | null
  now_n: number
  change: number | null
  better: boolean | null
  enough_data: boolean
  series: ValuePoint[]
  sentence: string
}

export type LungRecovery = {
  available: boolean
  reason: null | 'no_quit_date' | 'quit_date_in_future'
  quit_date: ISODate | null
  days_since_quit: number | null
  metrics: LungMetric[]
  milestones: Array<{ label: string; reached: boolean; at: ISODateTime }>
  note: string
}

export type WeeklyReport = {
  id: number
  week_start: ISODate
  week_end: ISODate
  generated_at: ISODateTime
  runs: { done: number; planned: number; planned_done: number; km: number; run_km: number; time_s: number; previous_done: number; previous_km: number }
  zones: Partial<Record<'Z1' | 'Z2' | 'Z3' | 'Z4' | 'Z5' | 'below', number>>
  zones_total_s: number
  prs: Array<{ key: string; label: string; display: string; date: ISODate | null }>
  wellness: Array<{ metric: string; label: string; unit: string; this_week: number | null; previous_week: number | null; delta: number | null; better: boolean | null }>
  habits: Array<{ habit: HabitKind; label: string; this_week: number; previous_week: number; delta: number; better: boolean | null }>
  went_well: string[]
  to_improve: string[]
  goal: string
  ai: { status: 'none' | 'ready'; markdown: string; generated_at: ISODateTime | null } | null
  /** R13 §10 */
  mood?: { mood_avg: number | null; energy_avg: number | null; days: number; previous_mood_avg: number | null; previous_energy_avg: number | null } | null
}

export type WeeklyReportListItem = { id: number; week_start: ISODate; week_end: ISODate; runs_done: number; km: number; generated_at: ISODateTime }

export type CompareMetric = { key: string; label: string; unit: string; group: 'wellness' | 'day' | 'habits' | 'runs' | (string & {}); noun: string }

export type CompareResult = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  x: { key: string; label: string; unit: string }
  y: { key: string; label: string; unit: string }
  range: string
  start: ISODate
  end: ISODate
  lag: number
  points: Array<{ date: ISODate; x: number; y: number }>
  n: number
  rho: number | null
  strength: 'none' | 'weak' | 'moderate' | 'strong' | null
  direction: 'positive' | 'negative' | null
  enough_data: boolean
  trend: { slope: number; intercept: number } | null
  sentence: string
  caveat: string
}

export type Reminder = { key: string; label: string; description: string; enabled: boolean; time: string | null }
export type RemindersResponse = {
  available: boolean; public_key: string | null; subscriptions: number; ios_note: string; reminders: Reminder[]
  /** R11 §C — move / breathing / water nudges (absent on an older server). */
  nudges?: Nudge[]
  quiet_hours?: { start: string; end: string }
  data_as_of?: string | null
}
export type NudgeKey = 'move' | 'breathing' | 'water'
export type Nudge = {
  key: NudgeKey; label: string; description: string; enabled: boolean
  start: string; end: string; max_per_day: number
  after_min: number | null; threshold: number | null; every_h: number | null
}

export type Badge = {
  key: string
  group: string
  label: string
  description: string
  target: number
  unit: string
  earned: boolean
  earned_on: ISODate | null
  progress: { current: number; target: number } | null
  new: boolean
}

export type Achievements = {
  badges: Badge[]
  recent: Array<{ key: string; kind: 'badge' | 'pr'; label: string; earned_on: ISODate }>
  unseen: number
}

export type ReadinessForecast = {
  date: ISODate
  estimate: number | null
  low: number | null
  high: number | null
  label: string
  is_estimate: true
  today: { score: number | null; source: 'garmin' | 'computed' | null } | null
  factors: Array<{ key: string; label: string; effect: number; detail: string }>
  levers: Array<{ key: string; label: string; gain: number }>
  best_case: number | null
  sentence: string
  note: string
}

export type HealthBody = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  range: string
  start: ISODate
  end: ISODate
  profile_weight_kg: number | null
  latest: null | { date: ISODate; weight_kg: number | null; body_fat_pct: number | null; bmi: number | null; muscle_mass_kg: number | null; source: 'garmin' | 'manual' }
  change: { weight_kg: number | null; body_fat_pct: number | null }
  trend_kg_per_week: number | null
  series: Array<{ date: ISODate; weight_kg: number | null; body_fat_pct: number | null; source: 'garmin' | 'manual' }>
}

// --- R11 (docs/API_NOTES.md "R11") ---------------------------------------------------

/** [minute of the local day, value] */
export type MinPoint = [number, number]
export type DayMarker = {
  type: 'run' | 'sleep' | 'nap' | 'habit'; start_min: number; end_min: number | null
  label: string; activity_id: number | null; kind: string | null
}
export type DayHour = { hour: number; label: string; steps: number }
export type DayStretch = { start: string; end: string; minutes: number; avg: number; peak: number }
export type BBEvent = {
  type: 'charge' | 'drain'; cause: 'sleep' | 'nap' | 'run' | 'stress' | 'rest' | 'activity'
  start: string; end: string; amount: number; from_value: number; to_value: number
}
export type HealthDay = {
  date: ISODate; is_today: boolean; available: boolean; complete: boolean
  /** R17: illness day — flagged, kept unless the athlete excludes it. */
  flagged?: { reason: string; text: string; illness_id?: number | null; decision: null | 'include' | 'exclude' } | null
  fetched_at: string | null; data_as_of: string | null
  prev_date: ISODate | null; next_date: ISODate | null
  awake: { start: string; end: string; source: 'sleep' | 'steps' | 'default' } | null
  timeline: { hr: MinPoint[]; stress: MinPoint[]; body_battery: MinPoint[]; steps: MinPoint[]; markers: DayMarker[] }
  steps: {
    total: number | null; goal: number | null; goal_source: 'garmin' | 'adaptive' | null
    adaptive_goal: number | null; pct: number | null; met: boolean | null; streak_days: number
    trend: { last7_avg: number | null; prev7_avg: number | null; change_pct: number | null }
    most_active_hour: DayHour | null; least_active_hour: DayHour | null; hourly: Array<{ hour: number; steps: number }>
    run_days_avg: number | null; rest_days_avg: number | null; run_days_n: number; rest_days_n: number
  }
  activity: {
    sedentary_min: number | null; active_min: number | null; intense_min: number | null; sleeping_min: number | null
    source: 'garmin' | 'steps' | null
    longest_sedentary: { minutes: number; start: string; end: string } | null
  }
  stress: {
    avg: number | null; max: number | null; rest_min: number; low_min: number; medium_min: number; high_min: number
    stressful_min: number; peak: { start: string; end: string; avg: number } | null; stretches: DayStretch[]
  }
  body_battery: {
    start: number | null; end: number | null; high: number | null; low: number | null
    charged: number | null; drained: number | null; at_wake: number | null; at_bedtime: number | null; now: number | null
    events: BBEvent[]
  }
  heart_rate: {
    resting: number | null; awake_min: number | null; awake_max: number | null; awake_avg: number | null
    trend: { this_week_avg: number | null; prev_week_avg: number | null; change: number | null }
  }
  score_card: { status: 'good' | 'ok' | 'low' | 'no_data'; sentence: string; bullets: string[]; tips: string[] }
  now: { steps: number | null; stress: number | null; stress_at: string | null; body_battery: number | null; body_battery_at: string | null }
}
export type DaySummary = {
  date: ISODate; available: boolean; steps: number | null; step_goal: number | null
  goal_source: 'garmin' | 'adaptive' | null; pct: number | null
  stress: number | null; stress_at: string | null; body_battery: number | null; body_battery_at: string | null
  data_as_of: string | null; fetched_at: string | null
}
export type DayTrendAvg = {
  steps: number | null; active_min: number | null; sedentary_min: number | null; stress_avg: number | null
  stress_high_min: number | null; awake_hr_avg: number | null; bb_at_bedtime: number | null
}
export type DayTrendRow = {
  date: ISODate; steps: number | null; step_goal: number | null; active_min: number | null; sedentary_min: number | null
  stress_avg: number | null; stress_high_min: number | null; stressful_min: number | null; awake_hr_avg: number | null
  bb_charged: number | null; bb_drained: number | null; bb_at_wake: number | null; bb_at_bedtime: number | null
}
export type DnrRow = {
  metric: string; label: string; unit: string; high: number | null; low: number | null
  n_high: number; n_low: number; diff: number | null; enough_data: boolean; sentence: string
}
export type DnrGroup = {
  key: 'stress' | 'steps' | (string & {}); label: string; split: number | null
  high_label: string; low_label: string; n_high: number; n_low: number; rows: DnrRow[]
}
export type DayTrends = {
  /** R12: the period the server used (absent before R12). */
  period?: ResponsePeriod | null
  range: string; start: ISODate; end: ISODate
  days: DayTrendRow[]; averages: DayTrendAvg; previous: DayTrendAvg
  weeks: Array<{ week_start: ISODate; n: number; steps_avg: number | null; active_min_avg: number | null; stress_avg: number | null; awake_hr_avg: number | null }>
  awake_hr_trend: { per_week: number | null; direction: 'up' | 'down' | 'flat' | null; sentence: string }
  weekday_pattern: {
    by_weekday: Array<{ weekday: number; label: string; n: number; steps_avg: number | null; stress_avg: number | null }>
    stress_peak_weekdays: { start: string; end: string; avg: number } | null
    stress_peak_weekends: { start: string; end: string; avg: number } | null
    sentence: string | null
  }
  goal_streak: number
  day_night_run: { caveat: string; groups: DnrGroup[] } | null
}

export type RoutePoint = {
  lat: number; lon: number; dist_m: number; t_s: number
  pace_s_per_km: number | null; hr: number | null; segment: 'run' | 'walk' | 'stop' | null; ele_m: number | null
}
export type ActivityRoute = {
  activity_id: number; available: boolean; reason: null | 'no_gps' | (string & {})
  hidden_endpoints: boolean; trimmed_m: number; total_distance_m: number; sampled_from: number
  bounds: { south: number; west: number; north: number; east: number } | null
  start: { lat: number; lon: number } | null; finish: { lat: number; lon: number } | null
  has_hr: boolean; has_elevation: boolean; has_segments: boolean
  pace_range: { min: number; max: number } | null; hr_range: { min: number; max: number } | null
  elevation: { gain_m: number; loss_m: number; min_m: number; max_m: number } | null
  km_markers: Array<{ km: number; lat: number; lon: number; index: number }>
  points: RoutePoint[]
}

// --- R12 §B: wake planner, my alarm, watch alarms (docs/API_NOTES.md "R12") ----------

/** 0 = Monday … 6 = Sunday. */
export type Weekday = 0 | 1 | 2 | 3 | 4 | 5 | 6

export type MyAlarm = {
  time: string | null
  days: number[]
  enabled: boolean
  /** Push notification at the alarm time — a notification, not a real alarm. */
  push: boolean
  run_time: string | null
  bedtime_reminder: boolean
  bedtime_lead_min: number
  push_available: boolean
  note: string
}

export type WatchAlarm = { time: string; days: number[]; once: boolean; enabled: boolean; label: string | null; device: string | null }

export type WatchAlarms = {
  available: boolean
  checked_on: ISODate | null
  alarms: WatchAlarm[]
  summary: string | null
}

export type WakeFlag = {
  kind: 'watch_alarm_after_run' | 'no_watch_alarm_for_run' | 'my_alarm_after_run' | 'no_alarm_for_run' | string
  text: string
}

export type WakePlan = {
  date: ISODate
  weekday: number
  run: {
    planned: boolean; workout_id: number | null; title: string | null; kind: string | null
    run_time: string | null; run_time_source: 'setting' | 'history' | null
  } | null
  need_s: number | null
  need_source: 'garmin' | 'default' | 'athlete' | 'user' | null
  wake_time: string | null
  wake_source: 'run' | 'habit' | 'default' | null
  bedtime: string | null
  bedtime_reminder_at: string | null
  my_alarm: MyAlarm | null
  my_alarm_on_date: string | null
  watch: WatchAlarms | null
  flags: WakeFlag[]
  android_intent: string | null
  sentence: string | null
}
