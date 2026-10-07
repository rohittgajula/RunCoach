/**
 * R13 §16: warm the lazily-loaded tabs once Today has painted, so the first tab switch
 * does not wait on the network. Idle-time only; a failure here is harmless (the route's
 * own lazy import retries on navigation).
 */
let done = false

export function preloadTabs() {
  if (done) return
  done = true
  const run = () => {
    void import('../pages/Calendar').catch(() => {})
    void import('../pages/Insights').catch(() => {})
    void import('../pages/Diet').catch(() => {})
    void import('../pages/Me').catch(() => {})
    void import('../pages/Chat').catch(() => {})
  }
  const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }
  if (w.requestIdleCallback) w.requestIdleCallback(run, { timeout: 4000 })
  else setTimeout(run, 2500)
}
