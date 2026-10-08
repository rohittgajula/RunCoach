/**
 * R16 (docs/API_NOTES.md "R16"): shared types plus the small pieces that live in the
 * main chunk — dated day metrics, auto-sync, plan-changed chips. The step editor and
 * the week tools (and their API calls) are in lazy chunks: lib/r16edit.ts.
 */
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, json } from './auth'
import { addDays, dayMonth, todayISO } from './format'
import { invalidatePlanData } from './queries'
import { isSyncing, setSyncing, useSyncing } from './syncFlag'
import type { ISODate, ISODateTime, SyncResult } from './types'

// --- §A types ------------------------------------------------------------------------

export type EditKind = 'warmup' | 'run' | 'walk' | 'recovery' | 'cooldown' | 'strides' | 'other'
export type StepTarget = 'hr' | 'pace' | 'none' | 'auto'

/** GET/PATCH /workouts/{id}/edit/ step. pace_low = the FAST edge (smaller s/km). */
export type EditStep = {
  kind: EditKind
  duration_s: number
  intensity?: 'walk' | 'easy' | 'moderate' | 'hard'
  target?: StepTarget
  hr_low?: number | null
  hr_high?: number | null
  pace_low?: number | null
  pace_high?: number | null
  note?: string | null
}
export type EditItem = EditStep | { repeat: number; steps: EditStep[] }

export type WatchEditStatus = 'not_on_watch' | 'updated' | 'unchanged' | 'pending' | 'failed'

// --- §B plan-changed chips -----------------------------------------------------------

/** Message.plan_changed item — summary like "Sat 12 Oct: 40 → 45 min". */
export type PlanChange = { workout_id: number; date: ISODate; summary: string }

export function invalidateAfterPlanChange(client: QueryClient) {
  invalidatePlanData(client)
  for (const key of ['today', 'briefing', 'adjustments', 'weather-suggestions']) client.invalidateQueries({ queryKey: [key] })
}

// --- §C dated day metrics ------------------------------------------------------------

export type Freshness = {
  as_of: ISODateTime
  today: ISODate
  stale: boolean
  stale_reason: 'sleep_missing' | 'readiness_missing' | 'both_missing' | null
  stale_text: string | null
  latest_sleep_date: ISODate | null
  latest_readiness_date: ISODate | null
  last_sync_at: ISODateTime | null
}

/**
 * "yesterday" / "7 Oct" when a day value isn't from today (or last night — Garmin dates a
 * night by the morning it ends, so last night's sleep is today's date). Fresh → ''.
 */
export function staleDateLabel(date: ISODate | null | undefined, today: ISODate = todayISO()): string {
  if (!date) return ''
  const d = date.slice(0, 10)
  if (d >= today) return ''
  if (d === addDays(today, -1)) return 'yesterday'
  return dayMonth(d)
}

/** Tiny muted "· yesterday" suffix; renders nothing for fresh values. */
export function DateSuffix({ date, className = '' }: { date: ISODate | null | undefined; className?: string }) {
  const label = staleDateLabel(date)
  if (!label) return null
  return <span className={`date-suffix ${className}`} title={`From ${label}`}> · {label}</span>
}

// --- §C auto-sync ------------------------------------------------------------------------

export type SyncStatus = {
  connected: boolean
  last_sync_at: ISODateTime | null
  last_attempt_at: ISODateTime | null
  running: boolean
  breaker_open: boolean
  can_sync_now: boolean
  /** Server-side: ≥ 05:00 local, last sync > 60 min, no attempt in 30 min, breaker closed. */
  auto_sync_due: boolean
  next_auto_sync_at: ISODateTime | null
  min_interval_s: number
}

const AUTO_KEY = 'rc.autosync.at'
/** Client-side spacing on top of the server's rule: at most one auto attempt per 30 min. */
const AUTO_SPACING_MS = 30 * 60_000
/** And don't ask /sync/status/ on every focus flick. */
const CHECK_SPACING_MS = 5 * 60_000

function lastAuto(): number {
  try { return Number(localStorage.getItem(AUTO_KEY)) || 0 } catch { return 0 }
}
function markAuto() {
  try { localStorage.setItem(AUTO_KEY, String(Date.now())) } catch { /* private mode: spacing is per load */ }
}

const SYNC_KEYS = [
  'garmin-status', 'sync-status', 'calendar', 'profile-summary', 'diet-day', 'calendar-month', 'insights', 'today',
  'briefing', 'checkins-pending', 'health-day', 'health-day-summary', 'health-body', 'health-fitness', 'training-status', 'health-sleep',
  'health-form', 'health-records', 'readiness-forecast', 'achievements', 'gear', 'lung-recovery', 'progress', 'habits-summary',
  'adjustments', 'workout',
]
export function refreshAfterSync(client: QueryClient) {
  for (const key of SYNC_KEYS) client.invalidateQueries({ queryKey: [key] })
}

type AutoSyncReply = Partial<SyncResult> & { skipped?: 'recent' | 'running' | 'breaker_open' | 'not_connected' | 'too_early'; status?: SyncStatus }

/**
 * R16 §C auto-sync: on open and on regaining focus, ask GET /sync/status/; when the
 * server says `auto_sync_due` (≥ 05:00 local, last sync > 60 min, no attempt in 30 min,
 * breaker closed) POST /garmin/sync/ {auto: true}. Silent on failure; refreshes the
 * affected queries when it imported something.
 */
export function useAutoSync(enabled: boolean) {
  const client = useQueryClient()
  const busy = useRef(false)
  const checkedAt = useRef(0)
  useEffect(() => {
    if (!enabled) return
    const check = async () => {
      if (busy.current || isSyncing() || document.visibilityState !== 'visible') return
      const now = Date.now()
      if (new Date().getHours() < 5 || now - checkedAt.current < CHECK_SPACING_MS || now - lastAuto() < AUTO_SPACING_MS) return
      busy.current = true
      checkedAt.current = now
      try {
        const status = await api<SyncStatus>('/sync/status/').catch(() => null)
        if (status) client.setQueryData(['sync-status'], status)
        if (!status?.auto_sync_due) return
        markAuto()
        setSyncing(true)
        try {
          const r = await api<AutoSyncReply>('/garmin/sync/', { method: 'POST', ...json({ auto: true, limit: 20 }) })
          if (r.status) client.setQueryData(['sync-status'], r.status)
          if (!r.skipped) refreshAfterSync(client)
        } finally {
          setSyncing(false)
        }
      } catch {
        /* auto-sync never shows an error; the Sync button does */
      } finally {
        busy.current = false
      }
    }
    const t = setTimeout(check, 1500)
    const onVis = () => { if (document.visibilityState === 'visible') void check() }
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('focus', onVis)
    return () => {
      clearTimeout(t)
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('focus', onVis)
    }
  }, [enabled, client])
}

/** Small "Syncing…" pill while any sync runs (auto or the Sync button). */
export function SyncingPill() {
  const on = useSyncing()
  const [shown, setShown] = useState(false)
  // Don't flash for a sync that finishes in a blink.
  useEffect(() => {
    if (!on) { setShown(false); return }
    const t = setTimeout(() => setShown(true), 250)
    return () => clearTimeout(t)
  }, [on])
  if (!shown) return null
  return <span className="syncing-pill" role="status"><span className="syncing-dot" aria-hidden="true" />Syncing…</span>
}
