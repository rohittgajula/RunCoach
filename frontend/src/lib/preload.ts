/**
 * R13 §16 + Smooth UI: one place that knows which chunk each route needs.
 *
 * The route's `lazy()` and the warmers below share the same promise, so a chunk warmed
 * at idle (or on the finger touching a tab) is already evaluated by the time React
 * renders the route — the old screen never has to wait on the network, and no
 * Suspense fallback flashes on a tab or section switch.
 */
import type { QueryClient } from '@tanstack/react-query'

type Loader<T = unknown> = () => Promise<T>

/** Memoise an import; a failed one (offline) is forgotten so the next try refetches. */
function once<T>(load: Loader<T>): Loader<T> {
  let p: Promise<T> | null = null
  return () => {
    if (!p) {
      p = load()
      p.catch(() => { p = null })
    }
    return p
  }
}

export const pages = {
  calendar: once(() => import('../pages/Calendar')),
  chat: once(() => import('../pages/Chat')),
  activities: once(() => import('../pages/Activities')),
  activityDetail: once(() => import('../pages/ActivityDetail')),
  insights: once(() => import('../pages/Insights')),
  me: once(() => import('../pages/Me')),
  weather: once(() => import('../pages/Weather')),
}

/** Health sections live with the Health chunk (lib/healthSections), not in the main one. */
const healthSections = once(() => import('./healthSections'))

/** A Health section's first-screen data (the helper ships with the Health chunk). */
export function prefetchHealth(client: QueryClient, key = 'overview') {
  void healthSections().then((m) => m.prefetchSection(client, key)).catch(() => undefined)
}

const SECTION_ORDER = [
  'day', 'sleep', 'fitness', 'habits', 'progress', 'more', 'dayTrends', 'guides',
  'goals', 'heart', 'body', 'labs',
] as const

const quiet = (p: Promise<unknown>) => p.catch(() => undefined)

/** Everything `path` needs to render without suspending. Resolves (never rejects) when warm. */
export function warmRoute(path: string): Promise<unknown> {
  const [, top = '', ...rest] = path.split('?')[0].split('/')
  switch (top) {
    case 'plan': return quiet(pages.calendar())
    case 'chat': return quiet(pages.chat())
    // /gym redirects to the plan now, so warm what it lands on.
    case 'gym': return quiet(pages.calendar())
    case 'me': return quiet(pages.me())
    case 'weather': return quiet(pages.weather())
    case 'health': {
      return quiet(Promise.all([pages.insights(), healthSections().then((m) => m.warmSection(rest))]))
    }
    default: return Promise.resolve()
  }
}

type IdleWindow = Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }
export function whenIdle(run: () => void, timeout = 4000) {
  const w = window as IdleWindow
  if (w.requestIdleCallback) w.requestIdleCallback(run, { timeout })
  else setTimeout(run, 1500)
}

let done = false

/**
 * Warm the lazily-loaded tabs once Today has painted, then every Health section, one
 * per idle slot so a slow phone never janks while it parses. A failure here is
 * harmless (the route's own lazy import retries on navigation).
 */
export function preloadTabs() {
  if (done) return
  done = true
  const queue: Loader[] = [
    pages.calendar, pages.activities, pages.insights, pages.chat, pages.me,
    ...SECTION_ORDER.map((key): Loader => () => healthSections().then((m): Promise<unknown> => m.sections[key]())),
    pages.weather,
  ]
  const next = () => {
    const load = queue.shift()
    if (!load) return
    void quiet(load()).then(() => whenIdle(next, 2000))
  }
  whenIdle(next)
}
