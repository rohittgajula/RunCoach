/**
 * R14 §14 staff admin API (docs/API_NOTES.md "R14 §14"). Its own module so it ships only
 * in the admin panel's chunk.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, json } from './auth'
import type { ISODate, ISODateTime } from './types'

const keep = <T,>(previous: T | undefined) => previous

// --- §14 admin ----------------------------------------------------------------------

export type AdminUser = {
  id: number
  username: string
  display_name: string
  email: string
  joined: ISODateTime
  last_active: ISODateTime | null
  is_active: boolean
  is_staff: boolean
  garmin_connected: boolean
  garmin_last_sync: ISODateTime | null
  plan: { id: number; name: string; race_date: ISODate | null } | null
  ai: { calls_month: number; cost_month_usd: number; budget: number; budget_source: 'default' | 'custom' } | null
}
export type Invite = {
  id: number
  code: string
  note: string
  max_uses: number
  uses: number
  expires_at: ISODateTime | null
  created_at: ISODateTime
  usable: boolean
  revoked: boolean
}
export type AiProvider = {
  key: 'openai' | 'gemini' | (string & {})
  label: string
  configured: boolean
  base_url: string | null
  features: { tools: boolean; json_schema: boolean; streaming: boolean; vision: boolean }
  models: string[]
}
export type AiTier = {
  tier: 'lite' | 'fast' | 'coach' | 'deep' | (string & {})
  provider: string
  model: string
  source: 'db' | 'env'
  env_provider: string
  env_model: string
  available: boolean
  updated_at: ISODateTime | null
}
export type AiPrice = { id: number; provider: string; model: string; input_per_m_usd: number; output_per_m_usd: number; note: string; updated_at: ISODateTime | null }
type Usage = { calls: number; errors: number; input_tokens: number; output_tokens: number; cost_usd: number }
export type AiStats = {
  range: string
  start: ISODate
  end: ISODate
  totals: Usage & { ok: number; refused: number; cached: number; error_rate: number; avg_latency_ms: number | null }
  month: { start: ISODate; calls: number; cost_usd: number; input_tokens: number; output_tokens: number }
  by_day: Array<Usage & { date: ISODate }>
  by_month: Array<Usage & { month: string }>
  by_tier: Array<Usage & { tier: string }>
  by_operation: Array<Usage & { operation: string; tier: string }>
  by_user: Array<Usage & { athlete_id: number | null; name: string }>
  by_model: Array<Usage & { provider: string; model: string; avg_latency_ms: number | null }>
  recent_errors: Array<{ at: ISODateTime; operation: string; provider: string; model: string; status: string; error: string }>
}
export type AdminSystem = {
  version: { git_sha: string | null; image: string | null; source: string | null } | null
  garmin: {
    breaker_open: boolean
    reason: string | null
    retry_after_s: number | null
    users: Array<{ athlete_id: number; name: string; connected: boolean; last_sync: ISODateTime | null; hours_since_sync: number | null; backfilled: boolean }>
  } | null
  celery: { available: boolean; queues: Array<{ name: string; length: number }> } | null
  backups: {
    available: boolean
    reason: string | null
    schedule: string | null
    last_success_at: ISODateTime | null
    last_schedule_at: ISODateTime | null
    jobs: Array<{ name: string; status: 'succeeded' | 'failed' | 'running' | (string & {}); started_at: ISODateTime | null; finished_at: ISODateTime | null }>
    r2: { configured: boolean | null; note: string } | null
  } | null
  kubernetes: {
    available: boolean
    reason: null | string
    nodes: Array<{
      name: string; ready: boolean; cpu_cores: number; cpu_used_cores: number | null; cpu_pct: number | null
      memory_bytes: number; memory_used_bytes: number | null; memory_pct: number | null
      disk_bytes: number | null; disk_allocatable_bytes: number | null
    }>
    pods: Array<{ name: string; app: string | null; phase: string; ready: boolean; restarts: number; started_at: ISODateTime | null; node: string | null }>
  } | null
  gcp: { configured: boolean; trial_end: ISODate | null; days_left: number | null; credit_inr: number | null } | null
  checked_at: ISODateTime
}

export const useAdminUsers = () =>
  useQuery({ queryKey: ['admin', 'users'], queryFn: () => api<{ registration_mode: string; default_budget: number; users: AdminUser[] }>('/admin/users/'), retry: false })
export const useAdminInvites = () => useQuery({ queryKey: ['admin', 'invites'], queryFn: () => api<Invite[]>('/admin/invites/'), retry: false })
export const useAiProviders = () => useQuery({ queryKey: ['admin', 'providers'], queryFn: () => api<AiProvider[]>('/admin/ai/providers/'), retry: false })
export const useAiConfig = () =>
  useQuery({ queryKey: ['admin', 'ai-config'], queryFn: () => api<{ tiers: AiTier[]; operations: Record<string, string> }>('/admin/ai/config/'), retry: false })
export const useAiPrices = () => useQuery({ queryKey: ['admin', 'prices'], queryFn: () => api<AiPrice[]>('/admin/ai/prices/'), retry: false })
export const useAiStats = (range: string) =>
  useQuery({ queryKey: ['admin', 'stats', range], queryFn: () => api<AiStats>(`/admin/ai/stats/?range=${range}`), placeholderData: keep, retry: false })
export const useAdminSystem = () =>
  useQuery({ queryKey: ['admin', 'system'], queryFn: () => api<AdminSystem>('/admin/system/'), retry: false, refetchInterval: 60_000 })

/** Every admin write: path + method + body; refreshes the admin reads afterwards. */
export function useAdminWrite<T = unknown>() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: 'POST' | 'PATCH' | 'PUT' | 'DELETE'; body?: unknown }) =>
      api<T>(path, { method, ...(body !== undefined ? json(body) : {}) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['admin'] }),
  })
}
