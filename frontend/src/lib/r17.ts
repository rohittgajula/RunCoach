/**
 * R17 (docs/API_NOTES.md "R17"): recovery routine, data check + data review, illness
 * mode, coach memory, deleting activities. Types and the small hooks used by main-chunk
 * cards; the timer, sheets and Me pages are lazy chunks.
 *
 * Rohit's rule: nothing is excluded or removed automatically — the app suggests, the
 * athlete decides, and every decision is reversible.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from './auth'
import type { ISODate, ISODateTime } from './types'

// --- §1 recovery routine ---------------------------------------------------------------

export type RecoveryStep = {
  key: string
  title: string
  /** Seconds per side when `per_side`. */
  seconds: number
  per_side: boolean
  cue: string
  figure: string
  optional: boolean
  softened?: boolean
  area?: string | null
}
export type RecoveryRoutine = {
  activity_id: number
  available: boolean
  reason_unavailable: null | 'not_a_run' | string
  minutes: number
  total_s: number
  reason: string
  focus: string[]
  steps: RecoveryStep[]
  avoided: Array<{ area: string; text: string }>
  notes: string[]
  done: boolean
  done_at: ISODateTime | null
  streak: { current: number; best: number } | null
  show_until: ISODateTime | null
}
export type RecoveryDone = {
  activity_id: number
  done: boolean
  done_at: ISODateTime
  streak: { current: number; best: number } | null
  new_badges: Array<{ key: string; label: string }>
}
export type RecoveryToday = {
  routine: null | { activity_id: number; minutes: number; title: string; show_until: ISODateTime; done: boolean }
}

/** Today card: the newest run still inside its 6-hour window and not done. */
export const useRecoveryToday = () =>
  useQuery({ queryKey: ['recovery-today'], queryFn: () => api<RecoveryToday>('/recovery/today/'), retry: false, staleTime: 5 * 60_000 })

// --- §2 data check + review ------------------------------------------------------------

export type QualityFlag = {
  kind: string
  start_s: number
  end_s: number
  severity: 'low' | 'medium' | 'high'
  fix: 'interpolated' | 'masked' | 'flagged'
  text: string
}
export type RunDecision = null | 'include' | 'exclude'
export type HrUse = 'cleaned' | 'raw'

export type ActivityQuality = {
  version?: number
  score: number
  status: 'clean' | 'fixed' | 'review'
  chip: string
  summary: string
  flags: QualityFlag[]
  counts?: Record<string, number>
  hr_fixed_s?: number
  gps_fixed_s?: number
  hr_fixed_pct?: number
  gps_fixed_pct?: number
  affected: string[]
  suggestion: 'exclude' | null
  suggestion_reason: string | null
  decision: RunDecision
  excluded_from_trends: boolean
  use: HrUse
  use_default?: HrUse
  use_choice: HrUse | null
  use_suggestion: 'cleaned' | null
  pending_review: boolean
  info?: string
}
export type QualitySeries = {
  activity_id: number
  quality: ActivityQuality | null
  series: Array<{ t: number; hr_raw: number | null; hr_clean: number | null; fixed: boolean }>
}

export type ReviewRun = {
  kind: 'run'; id: number; date: ISODate; title: string; score: number
  suggestion: 'exclude' | null; suggestion_reason: string | null; use_suggestion: 'cleaned' | null
  decision: RunDecision; use_choice: HrUse | null; pending: boolean; text: string
}
export type ReviewIllness = {
  kind: 'illness'; id: number; type: string; label: string; start: ISODate; end: ISODate
  days: Array<{ date: ISODate; decision: RunDecision; has_data: boolean }>
  decision: RunDecision | 'mixed'; pending: boolean; text: string
}
export type ReviewDeleted = {
  kind: 'deleted_in_garmin'; id: number; date: ISODate; title: string; detected_at: ISODateTime
  decision: null | 'remove' | 'keep'; pending: boolean; text: string
}
export type ReviewItem = ReviewRun | ReviewIllness | ReviewDeleted
export type DataReview = { pending: number; items: ReviewItem[] }

export type ReviewDecision =
  | { kind: 'run'; id: number; decision?: RunDecision; use?: HrUse | null }
  | { kind: 'day'; date: ISODate; decision: RunDecision }
  | { kind: 'illness'; id: number; decision: RunDecision }
  | { kind: 'deleted_in_garmin'; id: number; decision: 'remove' | 'keep' }

export const useDataReview = (all = false, enabled = true) =>
  useQuery({
    queryKey: ['data-review', all ? 'all' : 'pending'],
    queryFn: () => api<DataReview>(`/data-review/${all ? '?all=1' : ''}`),
    enabled,
    retry: false,
    staleTime: 5 * 60_000,
  })

/** Chip tone for the run sheet's "Data check". */
export function qualityTone(q: ActivityQuality): 'ok' | 'warn' | 'muted' {
  if (q.decision === 'exclude') return 'muted'
  if (q.pending_review || q.status === 'review') return 'warn'
  return q.status === 'clean' ? 'ok' : 'warn'
}
export function qualityChipText(q: ActivityQuality): string {
  if (q.decision === 'exclude') return 'Excluded by you'
  if (q.suggestion === 'exclude' && !q.decision) return 'Suggested: exclude?'
  return q.chip || (q.status === 'clean' ? 'Clean' : 'Fixed')
}

// --- deleting activities ---------------------------------------------------------------

export type DeletedActivity = {
  id: number
  garmin_activity_id: number | null
  date: ISODate
  sport: string
  distance_m: number | null
  deleted_at: ISODateTime
  reason: 'user' | 'deleted_in_garmin'
  can_reimport: boolean
}

// --- §10 illness -----------------------------------------------------------------------

export type IllnessType = 'cold' | 'flu' | 'stomach' | 'injury' | 'other'
export type ReturnSession = {
  workout_id: number | null
  date: ISODate
  title: string
  kind: 'EASY' | 'RUN_WALK' | string
  duration_s: number
  hr_cap: number | null
  pct_of_usual: number
  status: string | null
}
export type ReturnBlock = {
  rule: 'short' | 'week' | 'rebuild'
  label: string
  start: ISODate
  end: ISODate
  resumes_on: ISODate
  sessions: ReturnSession[]
  usual_duration_s: number
  note: string
}
export type Illness = {
  id: number
  type: IllnessType
  type_label: string
  symptoms: 'above_neck' | 'below_neck'
  fever: boolean
  start_date: ISODate
  expected_days: number | null
  note: string
  status: 'active' | 'recovered'
  recovered_on: ISODate | null
  days_off: number | null
  days_so_far: number
  paused_workouts: number
  advice: string[]
  see_doctor: string[]
  return_block: ReturnBlock | null
  race_warning: null | { race_id: number; name: string; date: ISODate; days_after_block: number; text: string }
  created_at?: ISODateTime
  updated_at?: ISODateTime
}
export type IllnessState = { active: Illness | null; history: Illness[] }
export type IllnessBody = {
  type: IllnessType
  symptoms?: 'above_neck' | 'below_neck'
  fever?: boolean
  start_date?: ISODate
  expected_days?: number | null
  note?: string
}

export const useIllness = () =>
  useQuery({ queryKey: ['illness'], queryFn: () => api<IllnessState>('/illness/'), retry: false, staleTime: 5 * 60_000 })

/** "Started by mistake": un-pauses everything, no return block. */
export const ILLNESS_LABEL: Record<string, string> = {
  cold: 'Cold', flu: 'Fever / flu', stomach: 'Stomach bug', injury: 'Injury', other: 'Other',
}

// --- §16 coach memory ------------------------------------------------------------------

export type CoachFact = {
  id: number
  text: string
  category: 'health' | 'schedule' | 'goals' | 'other'
  category_label?: string
  source: 'chat' | 'checkin' | 'app' | 'manual'
  pinned: boolean
  created_at: ISODateTime
  updated_at?: ISODateTime | null
  edited?: boolean
}
