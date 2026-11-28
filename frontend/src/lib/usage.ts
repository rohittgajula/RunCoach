/**
 * R26 §3: which screens actually get opened.
 *
 * The app has five tabs, thirteen pages and sixteen optional Today cards, and
 * there is no evidence about which of them are ever looked at. Deleting on a hunch
 * removes something that was being used; keeping everything is how a tool becomes
 * tiring to open. This records the opens so that decision can be made on data in a
 * fortnight's time.
 *
 * Two things it deliberately gets right:
 *
 * **"Used" means seen, not rendered.** A Today card that renders below the fold was
 * not looked at. Counting renders would report every card as used every single day,
 * which is exactly the answer that makes the data worthless. So cards report through
 * an IntersectionObserver and count only once they are actually on screen.
 *
 * **It costs nothing.** Writes happen during navigation, the moment the app has to
 * feel fastest, so nothing here touches the network on the hot path: events go into
 * an array, the array is flushed on a timer and when the tab is hidden, and a failed
 * flush is dropped rather than retried. Every entry point is wrapped — instrumentation
 * must never be able to break the screen it is measuring.
 */

import { useEffect, useRef } from 'react'
import { api, json } from './auth'

export type UsageKind = 'tab' | 'section' | 'card' | 'action'

/**
 * A pathname reduced to a key worth counting.
 *
 * Numeric and uuid-ish segments become `:id`, so a hundred visits to a hundred
 * different runs count as a hundred visits to the runs detail screen rather than
 * a hundred one-off keys. That keeps the data readable and means no row identifier
 * of his is ever stored here.
 */
export function routeKey(pathname: string): string {
  const parts = pathname.split('/').filter(Boolean).map((seg) => (
    /^\d+$/.test(seg) || /^[0-9a-f]{8}-[0-9a-f]{4}/i.test(seg) ? ':id' : seg.toLowerCase()
  ))
  return '/' + parts.join('/')
}
type Event = { key: string; kind: UsageKind; at: string }

const FLUSH_MS = 20_000
/** Same key again within this is the same visit — re-renders and route echoes. */
const DEDUPE_MS = 30_000
/** The server takes 60 per batch; holding more than that locally is pointless. */
const MAX_QUEUE = 60

let queue: Event[] = []
let lastSeen = new Map<string, number>()
let timer: ReturnType<typeof setInterval> | null = null
let started = false

function flush(): void {
  if (!queue.length) return
  const events = queue
  queue = []
  // Fire and forget. A dropped batch is a dropped batch; retrying would mean a
  // failing network turns into an ever-growing queue and repeated requests.
  //
  // `keepalive` is what makes the last flush of a session arrive at all. Without
  // it the browser is free to cancel an in-flight request as the page goes away,
  // which quietly loses the final screens of every single session — a bias in
  // exactly the data this exists to collect, and invisible unless you look for it.
  try {
    void api('/usage/', { method: 'POST', keepalive: true, ...json({ events }) })
      .catch(() => {})
  } catch {
    /* never let instrumentation surface an error */
  }
}

/** Called once from the app shell. Safe to call again. */
export function startUsage(): void {
  if (started || typeof window === 'undefined') return
  started = true
  try {
    timer = setInterval(flush, FLUSH_MS)
    // Hidden, not unload: iOS Safari frequently never fires unload, and this is
    // the only reliable moment to get the tail of a session out.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') flush()
    })
    window.addEventListener('pagehide', flush)
  } catch {
    /* no timers available is not an error worth surfacing */
  }
}

export function stopUsage(): void {
  if (timer) clearInterval(timer)
  timer = null
  started = false
}

export function track(kind: UsageKind, key: string): void {
  try {
    if (!key) return
    const id = `${kind}:${key}`
    const now = Date.now()
    const last = lastSeen.get(id)
    if (last && now - last < DEDUPE_MS) return
    lastSeen.set(id, now)
    // The map is per-session and tiny, but a long session visiting many keys
    // should not grow it without bound.
    if (lastSeen.size > 500) lastSeen = new Map([[id, now]])
    if (queue.length >= MAX_QUEUE) return
    queue.push({ kind, key, at: new Date(now).toISOString() })
  } catch {
    /* never let instrumentation surface an error */
  }
}

/**
 * Report a card as used once it is genuinely on screen.
 *
 * Returns a ref to put on the card's own element. Where IntersectionObserver is
 * unavailable the card is counted on mount instead, which overcounts — better than
 * a silent gap that would read as "never used".
 *
 * `child: true` observes the ref'd element's first element child instead of the
 * element itself, for a wrapper that is `display: contents` and so has no box of
 * its own to observe. That is how the Today cards are measured: a real wrapper
 * div would leave an empty box behind every card that renders null, and in a
 * `gap` layout that shows up as a phantom gap. It also behaves correctly at the
 * edge — a card that rendered nothing has no child, so nothing is observed and
 * nothing is counted, which is the truth.
 */
export function useSeen<T extends HTMLElement = HTMLDivElement>(
  kind: UsageKind, key: string, { child = false }: { child?: boolean } = {},
) {
  const ref = useRef<T | null>(null)
  const done = useRef(false)
  useEffect(() => {
    const host = ref.current
    const el = child ? (host?.firstElementChild as HTMLElement | null) : host
    if (done.current || !key) return
    if (!el || typeof IntersectionObserver === 'undefined') {
      // No element at all means the card rendered nothing, which is not a view.
      if (!el && child) return
      done.current = true
      track(kind, key)
      return
    }
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        // A third of the card on screen, so a sliver at the edge of a fast scroll
        // does not count as having been read.
        if (entry.isIntersecting && entry.intersectionRatio >= 0.33 && !done.current) {
          done.current = true
          track(kind, key)
          io.disconnect()
        }
      }
    }, { threshold: [0.33] })
    io.observe(el)
    return () => io.disconnect()
  }, [kind, key, child])
  return ref
}
