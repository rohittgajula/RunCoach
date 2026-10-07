import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png', 'apple-touch-icon.png'],
      manifest: {
        name: 'RunCoach',
        short_name: 'RunCoach',
        description: 'AI running coach — plan, chat, fuel',
        theme_color: '#f4f5f7',
        background_color: '#f4f5f7',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // The API is never precached. A cached training plan that silently disagrees
        // with the server is worse than an offline message.
        navigateFallbackDenylist: [/^\/api/, /^\/admin/],
        // R10 reminders: push + notificationclick handlers live in public/push-handler.js.
        importScripts: ['push-handler.js'],
      },
      // Off in development on purpose. A service worker caching assets while you
      // are editing them produces stale-bundle bugs that look like your change
      // simply did nothing. Verify the real worker against `npm run preview`.
      devOptions: { enabled: false },
    }),
  ],
  build: {
    // R13 §16: stable vendor chunks cache across deploys; app code changes don't
    // invalidate React. Charts and maps stay out of the first load entirely.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) return 'vendor-react'
          if (id.includes('@tanstack')) return 'vendor-query'
          if (/[\\/](recharts|d3-[^\\/]+|victory-vendor|decimal\.js-light|es-toolkit|redux|@reduxjs|reselect|immer|react-redux|use-sync-external-store|eventemitter3|clsx|tiny-invariant)[\\/]/.test(id)) return 'vendor-charts'
          if (id.includes('leaflet')) return 'vendor-map'
          return undefined
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Same-origin in development, so cookies work without CORS credentials games.
    proxy: {
      '/api': { target: process.env.VITE_PROXY_TARGET ?? 'http://backend:8000', changeOrigin: true },
    },
    // The HMR client connects from the browser on the HOST, so it must be told the
    // published port explicitly — inside the container Vite only knows about its own
    // bind address, and the websocket fails silently, leaving you reloading by hand.
    hmr: { clientPort: Number(process.env.VITE_HMR_PORT ?? 5174) },
    watch: {
      // Vite's native watcher misses newly created files under a bind mount, and the
      // symptom is a new component that simply never appears. This cost run-project
      // several restarts before it was diagnosed.
      usePolling: true,
    },
  },
})
