/**
 * R18 (docs/API_NOTES.md "R18") main-chunk pieces: the service-worker update flow, full
 * refresh (button, pull-to-refresh, phased progress) and the "everything changed" invalidation.
 */
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useState, useSyncExternalStore } from 'react'
import { ChipButton } from '../components/ChipButton'
import { RefreshIcon } from '../components/Icons'
import { api, json, onDataVersionChange } from './auth'
import { setSyncPhase, setSyncing, useSyncing } from './syncFlag'
import type { SyncResult } from './types'

// --- §B data_version → refetch everything ---------------------------------------------

/**
 * Every athlete query refetches (active ones now, the rest on next use). Auth lives
 * outside React Query, so "all queries" is exactly "all athlete data".
 */
export function invalidateAthleteData(client: QueryClient) {
  void client.invalidateQueries()
}

let dvTimer: ReturnType<typeof setTimeout> | undefined
/** Wired once from main.tsx: a mutation that bumped data_version refreshes all screens. */
export function wireDataVersion(client: QueryClient) {
  onDataVersionChange(() => {
    clearTimeout(dvTimer)
    // Coalesce a burst (save + its own invalidations) into one sweep.
    dvTimer = setTimeout(() => invalidateAthleteData(client), 150)
  })
}

// --- §A full sync -----------------------------------------------------------------------

export type SyncPhase = 'idle' | 'queued' | 'activities' | 'wellness' | 'intraday' | 'derived' | 'done' | 'failed'
/** GET /sync/status/ with the R18 additions (all optional: null-tolerant). */
export type FullSyncStatus = {
  running?: boolean
  phase?: SyncPhase | null
  progress?: number | null
  finished_at?: string | null
  job_id?: string | null
  error?: string | null
  min_interval_s?: number
  parts?: { activities?: { status: string; imported?: number } | null } | null
  run_aware?: { active?: boolean; waiting_for_run?: boolean; title?: string | null; run_time?: string | null; arrived?: boolean } | null
  data_version?: number
}
type FullSyncReply = Partial<SyncResult> & { job_id?: string; deduped?: boolean; mode?: string; status?: FullSyncStatus; skipped?: string }
const busyPhase = (p: SyncPhase | null | undefined) => !!p && p !== 'idle' && p !== 'done' && p !== 'failed'

let inflight: Promise<FullSyncReply> | null = null
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * POST /garmin/sync/ {full: true}, then follow /sync/status/ phases until done (max 3 min),
 * then refetch everything. Concurrent callers share one run.
 */
export function fullSync(client: QueryClient, auto = false): Promise<FullSyncReply> {
  if (inflight) return inflight
  inflight = (async () => {
    setSyncing(true)
    setSyncPhase(auto ? null : 'activities')
    try {
      const r = await api<FullSyncReply>('/garmin/sync/', { method: 'POST', ...json(auto ? { auto: true } : { full: true }) })
      let s = r.status
      if (s) client.setQueryData(['sync-status'], s)
      if (r.skipped) return r
      // The job runs on the server; follow its phases (max 3 min).
      let running = r.job_id != null && (!s || busyPhase(s.phase) || !!s.running)
      const until = Date.now() + 180_000
      if (s && busyPhase(s.phase)) setSyncPhase(s.phase)
      while (running && Date.now() < until) {
        await sleep(1500)
        const next = await api<FullSyncStatus>('/sync/status/').catch(() => null)
        if (!next) break
        s = next
        client.setQueryData(['sync-status'], s)
        if (busyPhase(s.phase)) setSyncPhase(s.phase)
        running = s.phase ? busyPhase(s.phase) : !!s.running
      }
      if (!auto) invalidateAthleteData(client) // auto: the status polls carry data_version
      if (s?.phase === 'failed') throw new Error(s.error || 'Sync stopped — Garmin is busy. Try again later.')
      return { ...r, imported: r.imported ?? s?.parts?.activities?.imported ?? 0 }
    } finally {
      setSyncing(false)
      setSyncPhase(null)
      inflight = null
    }
  })()
  return inflight
}

export function useSyncStatusR18() {
  return useQuery({ queryKey: ['sync-status'], queryFn: () => api<FullSyncStatus>('/sync/status/'), staleTime: 60_000 })
}

/** Header refresh chip (Today, Health). */
export function RefreshButton({ onDone }: { onDone?: (r: FullSyncReply | null, e?: unknown) => void }) {
  const client = useQueryClient()
  const syncing = useSyncing()
  const run = () => fullSync(client).then((r) => onDone?.(r), (e) => onDone?.(null, e))
  return (
    <ChipButton label="Refresh — sync everything from Garmin" onClick={run} disabled={syncing} className="chip-plain">
      <RefreshIcon className={syncing ? 'spin' : ''} />
    </ChipButton>
  )
}

/** Today: "Waiting for today's run…" while the run-aware auto-sync is polling. */
export function WaitingForRun() {
  const ra = useSyncStatusR18().data?.run_aware
  if (!ra?.waiting_for_run || ra.arrived) return null
  return (
    <p className="waiting-run" role="status">
      <span className="syncing-dot" aria-hidden="true" />Waiting for today’s run…{ra.title ? <span className="waiting-run-sub"> {ra.title}{ra.run_time ? ` · ${ra.run_time}` : ''}</span> : null}
    </p>
  )
}

/** Pull-to-refresh, loaded only on touch devices (lib/r18ptr.tsx). */
const PTR = lazy(() => import('./r18ptr'))
export function PullToRefresh() {
  if (typeof window === 'undefined' || !('ontouchstart' in window)) return null
  return <Suspense fallback={null}><PTR /></Suspense>
}

// --- §D service worker: never more than one open on an old bundle -------------------------

let updateReady = false
const swListeners = new Set<() => void>()
const loadedAt = Date.now()
let touched = false
let hiddenAt = 0

function reloadOnce() {
  // A deploy mid-reload must not loop: at most one automatic reload per 15 s.
  try {
    const last = Number(sessionStorage.getItem('rc.swreload')) || 0
    if (Date.now() - last < 15_000) return
    sessionStorage.setItem('rc.swreload', String(Date.now()))
  } catch { /* fine */ }
  location.reload()
}

/** Nothing half-done on screen: no field focused, no sheet open. */
const idle = () => !document.querySelector('input:focus, textarea:focus, select:focus, [role="dialog"]')

function markReady() {
  updateReady = true
  // Just opened and not touched yet (or in the background): take the new version now.
  if (document.visibilityState === 'hidden') return
  if (!touched && Date.now() - loadedAt < 10_000) return reloadOnce()
  swListeners.forEach((l) => l())
}

/**
 * The worker self-activates (skipWaiting + clientsClaim), so a new deploy takes over
 * as soon as it installs; this page then either reloads at once (fresh open, untouched),
 * on the next open (back from the background, idle) or when the athlete taps Reload.
 * Update checks run on every return to the app — an installed PWA resumed from the
 * background never navigates, so the browser alone would never look.
 */
export function initServiceWorker() {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return
  // An old page asking for a lazy chunk the deploy removed: reload into the new bundle.
  window.addEventListener('vite:preloadError', (e) => { e.preventDefault(); reloadOnce() })
  const mark = () => { touched = true }
  window.addEventListener('pointerdown', mark, { once: true, capture: true })
  window.addEventListener('keydown', mark, { once: true, capture: true })
  const sw = navigator.serviceWorker
  const hadController = !!sw.controller
  sw.addEventListener('controllerchange', () => { if (hadController) markReady() })
  const register = async () => {
    const reg = await sw.register('/sw.js', { scope: '/' }).catch(() => null)
    if (!reg) return
    // A worker left waiting by an older config: let it take over.
    if (reg.waiting && hadController) reg.waiting.postMessage({ type: 'SKIP_WAITING' })
    let checkedAt = Date.now()
    const check = () => {
      if (Date.now() - checkedAt < 60_000) return
      checkedAt = Date.now()
      void reg.update().catch(() => {})
    }
    setInterval(() => { if (document.visibilityState === 'visible') check() }, 30 * 60_000)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') { hiddenAt = Date.now(); return }
      // Next open: back after ≥ 30 s away, nothing half-done → new version.
      if (updateReady && idle() && Date.now() - hiddenAt > 30_000) return reloadOnce()
      check()
    })
  }
  if (document.readyState === 'complete') void register()
  else window.addEventListener('load', () => void register(), { once: true })
}

export function UpdateBanner() {
  const ready = useSyncExternalStore((l) => { swListeners.add(l); return () => { swListeners.delete(l) } }, () => updateReady)
  const [hidden, setHidden] = useState(false)
  if (!ready || hidden) return null
  return (
    <div className="update-banner" role="status">
      <span>Update available</span>
      <button type="button" className="update-reload" onClick={() => location.reload()}>Reload</button>
      <button type="button" className="update-x" aria-label="Later" onClick={() => setHidden(true)}>×</button>
    </div>
  )
}
