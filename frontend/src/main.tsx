import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AuthProvider } from './lib/AuthContext'
import { applyTheme, watchSystemTheme } from './lib/theme'
import '@fontsource/plus-jakarta-sans/latin-400.css'
import '@fontsource/plus-jakarta-sans/latin-500.css'
import '@fontsource/plus-jakarta-sans/latin-600.css'
import '@fontsource/plus-jakarta-sans/latin-700.css'
import '@fontsource/plus-jakarta-sans/latin-800.css'
import './styles/base.css'
import './styles/components.css'
import './styles/pages.css'
import './styles/insights.css'
import './styles/r10.css'
import './styles/r11.css'
import './styles/r12.css'
import './styles/r13.css'
import './styles/r14.css'
import './styles/r16.css'
import './styles/r17.css'
import './styles/motion.css'

// Before the first paint, so a dark-theme device never flashes white.
applyTheme()
watchSystemTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Smooth UI: keep a left tab's data for half an hour, so going back to it paints
      // the cached screen at once and refreshes in the background (stale-while-revalidate).
      gcTime: 30 * 60_000,
      retry: 1,
      // Coming back to the app after a run is exactly when data changed.
      refetchOnWindowFocus: true,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
