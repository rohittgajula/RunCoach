/* R10 web push: imported into the Workbox service worker (vite.config.ts → importScripts).
   Payload {title, body, url, tag} — never health numbers or habit counts. */
self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    data = { body: event.data ? event.data.text() : '' }
  }
  const title = data.title || 'RunCoach'
  // R15 run summary: "/activities/{id}" has no page of its own; the run is on Today.
  const url = /^\/activities\/\d+\/?$/.test(data.url || '') ? '/today' : data.url || '/today'
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || '',
      tag: data.tag || undefined,
      // A newer summary for the same run replaces the old one and still buzzes (so the
      // watch mirrors it). Never silent.
      renotify: !!(data.tag && data.kind === 'run_summary'),
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL((event.notification.data && event.notification.data.url) || '/today', self.location.origin).href
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.startsWith(self.location.origin) && 'focus' in client) {
          client.navigate(url)
          return client.focus()
        }
      }
      return self.clients.openWindow(url)
    }),
  )
})
