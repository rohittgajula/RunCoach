import type { MouseEvent } from 'react'
import type { NavigateFunction } from 'react-router-dom'
import { warmRoute } from './preload'

/**
 * Smooth UI: tab and Health-section switches as a short View Transition.
 *
 * The router already applies location changes inside a React transition, so the old
 * screen stays up until the new one has rendered. On top of that:
 *  1. the target chunk is warmed first (usually a no-op — idle preloading got there),
 *  2. `document.startViewTransition` freezes the old frame while React commits, then
 *     cross-fades/slides to the new one (≤200 ms, see styles/motion.css),
 *  3. a hard cap means a slow render can never hold the screen for long.
 * No View Transitions (older WebView), reduced motion or a hidden page → plain navigate.
 */
export type NavDir = 'fwd' | 'back' | 'fade'

type VTDocument = Document & {
  startViewTransition?: (update: () => Promise<void> | void) => { finished: Promise<void>; ready: Promise<void> }
}

let commitWaiter: (() => void) | null = null
let inFlight = false

/** Called by the Shell's layout effect whenever the location has committed to the DOM. */
export function routeCommitted() {
  const resolve = commitWaiter
  commitWaiter = null
  resolve?.()
}

export const reducedMotion = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const WARM_CAP_MS = 250
const COMMIT_CAP_MS = 350

export function navigateSmooth(navigate: NavigateFunction, to: string, dir: NavDir = 'fade') {
  const doc = document as VTDocument
  if (!doc.startViewTransition || reducedMotion() || document.visibilityState !== 'visible' || inFlight) {
    void warmRoute(to)
    navigate(to)
    return
  }
  inFlight = true
  const capped = (p: Promise<unknown>, ms: number) => Promise.race([p, new Promise((r) => setTimeout(r, ms))])
  void capped(warmRoute(to), WARM_CAP_MS).then(() => {
    const root = document.documentElement
    root.dataset.nav = dir
    try {
      const vt = doc.startViewTransition!(() => {
        const committed = new Promise<void>((resolve) => { commitWaiter = resolve })
        navigate(to)
        return capped(committed, COMMIT_CAP_MS).then(() => undefined)
      })
      // `ready` rejects when the browser skips the animation (page hidden, etc.); fine.
      vt.ready.catch(() => undefined)
      void vt.finished.catch(() => undefined).finally(() => {
        delete root.dataset.nav
        inFlight = false
      })
    } catch {
      delete root.dataset.nav
      inFlight = false
      navigate(to)
    }
  })
}

/** A plain left click with no modifiers — the only one we take over from the <a>. */
export function isPlainClick(event: MouseEvent) {
  return !event.defaultPrevented && event.button === 0 && !event.metaKey && !event.altKey && !event.ctrlKey && !event.shiftKey
}

/** Warm on intent: touch-down/hover/focus happen ~100 ms before the click lands. */
export function intentHandlers(to: string) {
  const warm = () => { void warmRoute(to) }
  return { onPointerDown: warm, onMouseEnter: warm, onFocus: warm }
}
