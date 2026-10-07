/**
 * R15 §A/§B admin API: model cards + status, check models, provider switch, per-tier
 * fallback, compare runs (docs/API_NOTES.md "R15"). Ships only in the admin chunk.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from './auth'
import type { ISODateTime } from './types'

export type ModelStatus = 'ok' | 'busy' | 'no_quota' | 'unavailable' | 'error' | 'unknown'
export type TierKey = 'lite' | 'fast' | 'coach' | 'deep'

export type ModelCard = {
  id: string
  priced: boolean
  status: ModelStatus
  checked_at: ISODateTime | null
  note: string | null
  label: string
  family: string
  known: boolean
  summary: string
  best_for: TierKey[]
  speed: 'fast' | 'medium' | 'slow'
  quality: 'basic' | 'good' | 'strong' | 'best'
  cost_level: 'free_tier' | '$' | '$$' | '$$$'
  price_in_per_1m: number | null
  price_out_per_1m: number | null
  est_cost_per_call_usd: Partial<Record<TierKey, number | null>>
  context_window: number | null
  free_tier_ok: boolean | null
  calls: number
  avg_latency_ms: number | null
  error_rate: number
  avg_cost_usd: number | null
}
export type ModelList = { provider: string; source: 'live' | 'price_table'; fetched_at: ISODateTime | null; models: ModelCard[] }

export type TierR15 = {
  tier: string
  provider: string
  model: string
  source: 'db' | 'env'
  env_provider: string
  env_model: string
  available: boolean
  updated_at: ISODateTime | null
  fallback_provider?: string | null
  fallback_model?: string | null
  fallback?: { provider: string; model: string; source: 'db' | 'env' } | null
  model_status?: ModelStatus
  warning?: string | null
}
export type ConfigR15 = { tiers: TierR15[]; operations: Record<string, string> }
export type SwitchResult = ConfigR15 & { changed: Array<{ tier: string; model: string }>; unchanged: Array<{ tier: string; reason: string }> }

export type CompareResult = {
  index: number
  provider: string
  model: string
  ok: boolean
  status: 'ok' | 'error'
  error_kind: string | null
  error: string | null
  hint: string | null
  text: string
  latency_ms: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  rating: number | null
}
export type CompareRun = {
  id: number
  created_at: ISODateTime
  created_by: { id: number; username: string } | null
  prompt: string
  operation: 'insights_summary' | 'run_review' | null
  context_note: string | null
  results: CompareResult[]
}

export const useModelCards = (provider: string, poll = false) =>
  useQuery({
    queryKey: ['admin', 'models', provider],
    queryFn: () => api<ModelList>(`/admin/ai/models/?provider=${encodeURIComponent(provider)}`),
    enabled: !!provider,
    retry: false,
    staleTime: 60_000,
    refetchInterval: poll ? 5_000 : false,
  })

export const useCompareHistory = () =>
  useQuery({ queryKey: ['admin', 'compare'], queryFn: () => api<CompareRun[]>('/admin/ai/compare/?limit=20'), retry: false })

export const STATUS_TEXT: Record<ModelStatus, string> = {
  ok: 'Works', busy: 'Busy', no_quota: 'Needs billing', unavailable: 'Unavailable', error: 'Error', unknown: 'Not checked',
}
