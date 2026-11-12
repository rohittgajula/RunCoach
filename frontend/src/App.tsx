import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { Shell } from './components/Shell'
import { Loading } from './components/States'
import { useAuth } from './lib/AuthContext'
import { pages } from './lib/preload'
import Today from './pages/Today'

// R13 §16: Today is the first screen, so it stays in the main chunk; every other tab
// (and the auth/onboarding screens a signed-in user never sees) loads on demand.
// Smooth UI: the loaders are shared with lib/preload, so a chunk warmed at idle or on
// touch-down is the very promise the route renders from.
const Plan = lazy(pages.calendar)
const Chat = lazy(pages.chat)
const ChatIndex = lazy(() => pages.chat().then((m) => ({ default: m.ChatIndex })))
const Health = lazy(pages.insights)
const Me = lazy(pages.me)
// R14: weather report and the staff-only admin panel, each its own chunk.
const Weather = lazy(pages.weather)
const AdminPanel = lazy(() => import('./pages/AdminPanel'))
const Onboarding = lazy(() => import('./pages/Onboarding'))
const Login = lazy(() => import('./pages/Auth').then((m) => ({ default: m.Login })))
const Register = lazy(() => import('./pages/Auth').then((m) => ({ default: m.Register })))

const pageFallback = <div className="page centered"><Loading block /></div>


/**
 * Three gates, in order: signed in, onboarded, then the five tabs. Onboarding is an
 * explicit flag on the athlete rather than inferred — racing a redirect against a state
 * update once skipped it entirely.
 */
function RequireAuth({ children }: { children: ReactNode }) {
  const { athlete, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page centered"><Loading block /></div>
  if (!athlete) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (!athlete.onboarding_complete && location.pathname !== '/onboarding') {
    return <Navigate to="/onboarding" replace />
  }
  return <>{children}</>
}

/** R14 §14: the admin panel exists only for staff; everyone else lands on Today. */
function StaffOnly({ children }: { children: ReactNode }) {
  const { isStaff, staffPending } = useAuth()
  if (staffPending) return pageFallback
  if (!isStaff) return <Navigate to="/today" replace />
  return <>{children}</>
}

function GuestOnly({ children }: { children: ReactNode }) {
  const { athlete, loading } = useAuth()
  if (loading) return <div className="page centered"><Loading block /></div>
  if (athlete) return <Navigate to="/today" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Suspense fallback={pageFallback}>
    <Routes>
      <Route path="/login" element={<GuestOnly><Login /></GuestOnly>} />
      <Route path="/register" element={<GuestOnly><Register /></GuestOnly>} />
      <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Shell>
              <Suspense fallback={pageFallback}>
              <Routes>
                <Route path="/today" element={<Today />} />
                <Route path="/plan" element={<Plan />} />
                <Route path="/chat" element={<ChatIndex />} />
                <Route path="/chat/:threadId" element={<Chat />} />
                {/* Removed from the tab bar; kept as a redirect for old links. */}
                <Route path="/diet" element={<Navigate to="/today" replace />} />
                <Route path="/health/*" element={<Health />} />
                <Route path="/me/*" element={<Me />} />
                <Route path="/weather" element={<Weather />} />
                <Route path="/admin-panel/*" element={<StaffOnly><AdminPanel /></StaffOnly>} />
                {/* Pre-R10 routes. */}
                <Route path="/calendar" element={<Navigate to="/plan" replace />} />
                <Route path="/insights" element={<OldInsights />} />
                <Route path="/insights/:section" element={<OldInsights />} />
                <Route path="/profile" element={<Navigate to="/me" replace />} />
                <Route path="*" element={<Navigate to="/today" replace />} />
              </Routes>
              </Suspense>
            </Shell>
          </RequireAuth>
        }
      />
    </Routes>
    </Suspense>
  )
}

/** /insights/habits?x → /health/habits?x (guides keep their ?g=). */
function OldInsights() {
  const { section } = useParams()
  const { search } = useLocation()
  return <Navigate to={`/health${section ? `/${section}` : ''}${search}`} replace />
}
