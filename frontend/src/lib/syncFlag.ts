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
