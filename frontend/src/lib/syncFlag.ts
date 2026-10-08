import { useSyncExternalStore } from 'react'

/** R16 §C: one global "a Garmin sync is running" flag (auto-sync and every Sync button). */
let syncing = 0
const listeners = new Set<() => void>()
export const setSyncing = (on: boolean) => {
  syncing = Math.max(0, syncing + (on ? 1 : -1))
  listeners.forEach((l) => l())
}
export const isSyncing = () => syncing > 0
export const useSyncing = () =>
  useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l) } }, isSyncing)

/** R18 §D: the current phase of a full sync, for the progress pill ("Syncing sleep…"). */
let phase: string | null = null
const phaseListeners = new Set<() => void>()
export const setSyncPhase = (p: string | null | undefined) => {
  if ((p ?? null) === phase) return
  phase = p ?? null
  phaseListeners.forEach((l) => l())
}
export const useSyncPhase = () =>
  useSyncExternalStore((l) => { phaseListeners.add(l); return () => { phaseListeners.delete(l) } }, () => phase)
const PHASE_TEXT: Record<string, string> = {
  activities: 'Syncing activities…', wellness: 'Syncing sleep…', intraday: 'Syncing day data…', derived: 'Updating insights…',
}
export const phaseText = (p: string | null) => (p && PHASE_TEXT[p]) || 'Syncing…'
