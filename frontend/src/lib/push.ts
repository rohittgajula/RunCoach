/**
 * R10 reminders — Web Push. The service worker (Workbox + public/push-handler.js) shows
 * the notification; this module asks permission and hands the subscription to the API.
 */

export const pushSupported = () =>
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

export const isIOS = () => {
  const ua = navigator.userAgent
  return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
}

export const isStandalone = () =>
  window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true

/** The active registration, or null when no worker controls the app (e.g. `npm run dev`). */
export async function registration(timeoutMs = 3000): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null
  const existing = await navigator.serviceWorker.getRegistration()
  if (existing?.active) return existing
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
  ])
}

function keyBytes(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await registration(1500)
  return reg ? reg.pushManager.getSubscription() : null
}

export type SubscribeOutcome =
  | { ok: true; subscription: PushSubscription }
  | { ok: false; reason: 'unsupported' | 'no-worker' | 'denied' | 'failed'; message?: string }

export async function subscribe(publicKey: string): Promise<SubscribeOutcome> {
  if (!pushSupported()) return { ok: false, reason: 'unsupported' }
  const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
  if (permission !== 'granted') return { ok: false, reason: 'denied' }
  const reg = await registration()
  if (!reg) return { ok: false, reason: 'no-worker' }
  try {
    const existing = await reg.pushManager.getSubscription()
    const subscription = existing ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }))
    return { ok: true, subscription }
  } catch (error) {
    return { ok: false, reason: 'failed', message: error instanceof Error ? error.message : undefined }
  }
}
