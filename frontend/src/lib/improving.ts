import { useQuery } from '@tanstack/react-query'
import { api } from './auth'
import type { ISODate } from './types'

export type ImprovingRun = {
  date: ISODate; total_min: number; total_km: number; run_min: number; run_pace_s: number | null
  run_hr: number | null; max_hr: number | null; m_per_beat: number | null; z2_pct: number | null
  z45_pct: number | null; zones_pct: Record<'below' | 'Z1' | 'Z2' | 'Z3' | 'Z4' | 'Z5', number | null>
  longest_run_min: number; short: boolean
}
export type ImprovingMonth = {
  month: string; runs: number; run_hr: number | null; max_hr: number | null; m_per_beat: number | null
  z45_pct: number | null; z2_pct: number | null; run_pace_s: number | null; run_min: number | null; rhr: number | null
}
export type ImprovingChange = { key: 'z45_pct' | 'run_hr' | 'm_per_beat' | 'run_pace_s' | 'rhr' | 'max_hr'; start: number | null; end: number | null; status: 'better' | 'worse' | 'flat' | 'unknown' }
export type ImprovingReport = {
  status: 'ok' | 'not_enough'
  runs: ImprovingRun[]; months: ImprovingMonth[]; changes: ImprovingChange[]
  verdict: { key: string; title: string; text: string }
  from_month?: string; to_month?: string
  excluded_indoor: number; easy_band: [number, number] | null
  gaps: Array<{ from: ISODate; to: ISODate | null; days: number }>
  mpb_goal?: [number, number] | null
  zones: Array<{ name: string; low: number; high: number }> | null
  first: ISODate | null; last: ISODate | null
}

/** Health → Reports → Improving. Built on read from stored runs; cheap. */
export const useImprovingReport = () =>
  useQuery({ queryKey: ['improving-report'], queryFn: () => api<ImprovingReport>('/reports/improving/'), staleTime: 5 * 60_000 })
