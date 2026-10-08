/**
 * R17 mutations and helpers used only by lazy screens (timer, sheets, Me pages) — kept
 * out of the main chunk. Types and the read hooks Today needs live in r17.ts.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, json } from './auth'
import { invalidatePlanData } from './queries'
import type {
  ActivityQuality, HrUse, RecoveryRoutine, Illness, IllnessBody, QualitySeries, RecoveryDone, ReviewDecision, ReviewItem, RunDecision,
} from './r17'

const DELETE_KEYS = [
  'calendar', 'calendar-month', 'calendar-day', 'today', 'briefing', 'workout', 'activity', 'progress', 'heart', 'insights',
  'health-records', 'health-form', 'health-fitness', 'achievements', 'gear', 'recovery-today', 'data-review', 'activities-deleted',
  'profile-summary', 'checkins-pending', 'compliance', 'weekly-report',
]
const REVIEW_KEYS = [
  'data-review', 'activity', 'quality', 'progress', 'heart', 'insights', 'health-day', 'health-day-summary', 'day-trends',
  'health-body', 'health-fitness', 'health-form', 'health-records', 'compare', 'run-review', 'route',
]

export const useRecovery = (activityId: number | null, enabled = true) =>
  useQuery({
    queryKey: ['recovery', activityId],
    queryFn: () => api<RecoveryRoutine>(`/activities/${activityId}/recovery/`),
    enabled: enabled && activityId != null,
    retry: false,
    staleTime: 10 * 60_000,
  })

export function useRecoveryDone(activityId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (skipped: string[]) =>
      api<RecoveryDone>(`/activities/${activityId}/recovery/done/`, { method: 'POST', ...json(skipped.length ? { skipped } : {}) }),
    onSuccess: () => {
      for (const key of ['recovery', 'recovery-today', 'achievements']) client.invalidateQueries({ queryKey: [key] })
    },
  })
}

export const useQualitySeries = (activityId: number | null, enabled = true) =>
  useQuery({
    queryKey: ['quality', activityId],
    queryFn: () => api<QualitySeries>(`/activities/${activityId}/quality/`),
    enabled: enabled && activityId != null,
    retry: false,
  })

export function refreshAfterReview(client: QueryClient) {
  for (const key of REVIEW_KEYS) client.invalidateQueries({ queryKey: [key] })
}

/** PATCH /activities/{id}/quality/ — `null` resets to undecided / default. */
export function usePatchQuality(activityId: number) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { decision?: RunDecision; use?: HrUse | null }) =>
      api<{ activity_id: number; quality: ActivityQuality }>(`/activities/${activityId}/quality/`, { method: 'PATCH', ...json(body) }),
    onSuccess: () => refreshAfterReview(client),
  })
}

export function useDecideReview() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (items: ReviewDecision[]) =>
      api<{ updated: number; items: ReviewItem[] }>('/data-review/decide/', { method: 'POST', ...json({ items }) }),
    onSuccess: (_d, items) => {
      refreshAfterReview(client)
      if (items.some((i) => i.kind === 'deleted_in_garmin' && i.decision === 'remove')) refreshAfterDelete(client)
    },
  })
}

export function refreshAfterDelete(client: QueryClient) {
  invalidatePlanData(client)
  for (const key of DELETE_KEYS) client.invalidateQueries({ queryKey: [key] })
}

export function useDeleteActivity() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<{ deleted: number; tombstone_id: number; workouts_reopened: number[]; records_removed: string[] }>(`/activities/${id}/`, { method: 'DELETE' }),
    onSuccess: () => refreshAfterDelete(client),
  })
}

export function refreshAfterIllness(client: QueryClient) {
  invalidatePlanData(client)
  for (const key of ['illness', 'today', 'briefing', 'adjustments', 'weather-suggestions', 'data-review', 'strength', 'achievements']) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useStartIllness() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: IllnessBody) => api<Illness>('/illness/', { method: 'POST', ...json(body) }),
    onSuccess: () => refreshAfterIllness(client),
  })
}

export function useRecover(id: number | null | undefined) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (dryRun: boolean) => api<Illness>(`/illness/${id}/recover/`, { method: 'POST', ...json({ dry_run: dryRun }) }),
    onSuccess: (_d, dryRun) => { if (!dryRun) refreshAfterIllness(client) },
  })
}

export function useCancelIllness() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/illness/${id}/`, { method: 'DELETE' }),
    onSuccess: () => refreshAfterIllness(client),
  })
}
