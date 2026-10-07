import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { Shell } from './components/Shell'
import { Loading } from './components/States'
import { useAuth } from './lib/AuthContext'
import Plan from './pages/Calendar'
import Chat, { ChatIndex } from './pages/Chat'
import Diet from './pages/Diet'
import Health from './pages/Insights'
import { Login, Register } from './pages/Auth'
import Me from './pages/Me'
import Onboarding from './pages/Onboarding'
import Today from './pages/Today'

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

function GuestOnly({ children }: { children: ReactNode }) {
  const { athlete, loading } = useAuth()
  if (loading) return <div className="page centered"><Loading block /></div>
  if (athlete) return <Navigate to="/today" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<GuestOnly><Login /></GuestOnly>} />
      <Route path="/register" element={<GuestOnly><Register /></GuestOnly>} />
      <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Shell>
              <Routes>
                <Route path="/today" element={<Today />} />
                <Route path="/plan" element={<Plan />} />
                <Route path="/chat" element={<ChatIndex />} />
                <Route path="/chat/:threadId" element={<Chat />} />
                <Route path="/diet" element={<Diet />} />
                <Route path="/health/*" element={<Health />} />
                <Route path="/me/*" element={<Me />} />
                {/* Pre-R10 routes. */}
                <Route path="/calendar" element={<Navigate to="/plan" replace />} />
                <Route path="/insights" element={<OldInsights />} />
                <Route path="/insights/:section" element={<OldInsights />} />
                <Route path="/profile" element={<Navigate to="/me" replace />} />
                <Route path="*" element={<Navigate to="/today" replace />} />
              </Routes>
            </Shell>
          </RequireAuth>
        }
      />
    </Routes>
  )
}

/** /insights/habits?x → /health/habits?x (guides keep their ?g=). */
function OldInsights() {
  const { section } = useParams()
  const { search } = useLocation()
  return <Navigate to={`/health${section ? `/${section}` : ''}${search}`} replace />
}
