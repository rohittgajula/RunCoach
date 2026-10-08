/**
 * R16 §A edit endpoints (docs/API_NOTES.md "R16 §A"). Only the lazy step editor and the
 * lazy week-edit sheet import this.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from './auth'
import { invalidateAfterPlanChange, type EditItem, type WatchEditStatus } from './r16'
import type { ISODate, Workout } from './types'

export type Brief = { title: string; duration_s: number; run_s: number; walk_s: number }
export type EditWarning = { key: 'run_increase' | 'hr_above_ceiling' | 'hard_days_in_a_row' | 'long_run_share' | (string & {}); text: string }

export type EditModel = {
  workout_id: number
  date: ISODate
  title: string
  kind: string
  editable: boolean
  notes_only: boolean
  reason: string | null
  notes: string
  total_s: number
  run_s: number
  walk_s: number
  steps: EditItem[]
  planned: { title: string; kind: string; duration_s: number; run_s: number } | null
  edited_by: 'user' | null
  limits: {
    total_min_s: number; total_max_s: number; step_min_s: number; step_max_s: number
    repeat_min: number; repeat_max: number; max_steps: number
    hr_min: number; hr_max: number; pace_min_s: number; pace_max_s: number
  }
  hr: { resting: number | null; max: number | null; ceiling: number; easy_low: number; easy_high: number }
  pace: { easy_low: number; easy_high: number }
}

export const useEditModel = (id: number, enabled = true) =>
  useQuery({
    queryKey: ['workout-edit', id],
    queryFn: () => api<EditModel>(`/workouts/${id}/edit/`),
    enabled,
    staleTime: 0,
    gcTime: 60_000,
  })

export type WorkoutEditBody = {
  steps?: EditItem[]
  total_minutes?: number
  add_minutes?: number
  apply_to?: 'run' | 'walk' | 'both'
  add_walk_breaks?: number
  hr_low?: number
  hr_high?: number
  notes?: string
  dry_run?: boolean
}

export type EditResponse = Workout & {
  warnings: EditWarning[]
  edit: { dry_run: boolean; changed: boolean; before: Brief; after: Brief; summary: string }
  watch: { was_on_watch: boolean; status: WatchEditStatus; detail: string }
}

/** Strip the edit-only keys so the cache holds a plain Workout. */
const workoutOf = ({ warnings: _w, edit: _e, watch: _x, ...w }: EditResponse): Workout => w

export function useEditWorkout(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: WorkoutEditBody) => api<EditResponse>(`/workouts/${id}/edit/`, { method: 'PATCH', ...json(body) }),
    onSuccess: (r, body) => {
      if (body.dry_run) return
      client.setQueryData(['workout', id], workoutOf(r))
      client.removeQueries({ queryKey: ['workout-edit', id] })
      invalidateAfterPlanChange(client)
    },
  })
}

export function useUndoEdit(id: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<EditResponse>(`/workouts/${id}/edit/undo/`, { method: 'POST' }),
    onSuccess: (r) => {
      client.setQueryData(['workout', id], workoutOf(r))
      client.removeQueries({ queryKey: ['workout-edit', id] })
      invalidateAfterPlanChange(client)
    },
  })
}

/** The toast after a save, from `watch.status`. */
export function watchToast(r: EditResponse, restored = false): string {
  const done = restored ? 'Plan version restored' : 'Saved'
  switch (r.watch?.status) {
    case 'updated': return 'Updated on watch ✓'
    case 'unchanged': return `${done} · watch already up to date`
    case 'pending': return `${done} · updating your watch…`
    case 'failed': return `${done} — the watch wasn’t updated`
    default: return done
  }
}

// --- week tools ------------------------------------------------------------------------

export type WeekAction = 'add_minutes' | 'scale' | 'add_walk_breaks' | 'set_hr_range'

export type WeekEditBody = {
  week_start: ISODate
  action: WeekAction
  /** add_minutes: −60…60 · scale: 0.5–1.5 · add_walk_breaks: 1–30 run minutes · set_hr_range: {hr_low, hr_high} */
  value: number | { hr_low: number; hr_high: number }
  apply_to?: 'run' | 'walk' | 'both'
  kinds?: string[]
  dry_run?: boolean
}

export type WeekEditResult = {
  week_start: ISODate
  week_end: ISODate
  action: WeekAction
  dry_run: boolean
  changed: Array<{ workout_id: number; date: ISODate; title: string; before: Brief; after: Brief; summary: string }>
  skipped: Array<{ workout_id: number; date: ISODate; title: string; reason: string }>
  warnings: Array<{ workout_id: number; date: ISODate; key: string; text: string }>
  watch: { updated: number; unchanged: number; pending: number; failed: number; not_on_watch: number }
}

export function useWeekEdit() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: WeekEditBody) => api<WeekEditResult>('/plan/week-edit/', { method: 'POST', ...json(body) }),
    onSuccess: (_r, body) => {
      if (!body.dry_run) invalidateAfterPlanChange(client)
    },
  })
}
