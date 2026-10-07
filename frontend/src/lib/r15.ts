/**
 * R15 share data (docs/API_NOTES.md "R15 §D"). Only the lazy share studio imports this.
 */
import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from './auth'
import type { ISODate, ISODateTime } from './types'

export type ShareData = {
  activity_id: number
  sport: string
  title: string
  workout_title: string | null
  date: ISODate
  started_at: ISODateTime
  start_local: string
  distance_m: number
  distance_km: number
  moving_s: number
  elapsed_s: number
  avg_pace_s_per_km: number | null
  run_pace_s_per_km: number | null
  avg_hr: number | null
  max_hr: number | null
  cadence_spm: number | null
  elevation_gain_m: number | null
  calories: number | null
  splits: Array<{ km: number; pace_s: number; hr: number | null; distance_m: number; partial: boolean }>
  best_km: { km: number; pace_s: number } | null
  weather: { temp_c: number | null; feels_like_c: number | null; humidity: number | null; dew_point_c: number | null } | null
  route: {
    available: boolean
    reason: string | null
    hidden_endpoints: boolean
    trimmed_m: number
    bounds: { south: number; west: number; north: number; east: number } | null
    points: Array<[number, number]>
    km_markers: Array<{ km: number; lat: number; lon: number }>
  }
}

/** null when the server has no share-data endpoint yet (older backend) — the studio falls back. */
export const useShareData = (id: number) =>
  useQuery({
    queryKey: ['share-data', id],
    queryFn: async () => {
      try {
        return await api<ShareData>(`/activities/${id}/share-data/`)
      } catch (e) {
        if (e instanceof ApiError && [404, 405, 501].includes(e.status)) return null
        throw e
      }
    },
    retry: false,
    staleTime: 10 * 60_000,
  })
