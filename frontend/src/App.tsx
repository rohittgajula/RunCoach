import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Shell } from './components/Shell'
import { Loading } from './components/States'
import { useAuth } from './lib/AuthContext'
import Calendar from './pages/Calendar'
import Chat, { ChatIndex } from './pages/Chat'
import Diet from './pages/Diet'
import Insights from './pages/Insights'
import { Login, Register } from './pages/Auth'
import Onboarding from './pages/Onboarding'
import Profile from './pages/Profile'

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
  if (athlete) return <Navigate to="/calendar" replace />
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
                <Route path="/calendar" element={<Calendar />} />
                <Route path="/chat" element={<ChatIndex />} />
                <Route path="/chat/:threadId" element={<Chat />} />
                <Route path="/diet" element={<Diet />} />
                <Route path="/insights" element={<Insights />} />
                <Route path="/profile" element={<Profile />} />
                <Route path="*" element={<Navigate to="/calendar" replace />} />
              </Routes>
            </Shell>
          </RequireAuth>
        }
      />
    </Routes>
  )
}
