import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react'
import { api, json, onDataVersionChange, restoreSession, setAccessToken, type Athlete, type Session } from './auth'

type AuthValue = {
  athlete: Athlete | null
  username: string | null
  /** R14 §14: staff see the admin panel. Read from the session; false when absent. */
  isStaff: boolean
  /** True while a staff check is still running (old session payloads only). */
  staffPending: boolean
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  register: (input: RegisterInput) => Promise<void>
  logout: () => Promise<void>
  deleteAccount: (password: string) => Promise<void>
  updateAthlete: (patch: Partial<Athlete>) => Promise<Athlete>
}

export type RegisterInput = {
  username: string
  password: string
  email?: string
  display_name?: string
  timezone?: string
  invite_code?: string
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [athlete, setAthlete] = useState<Athlete | null>(null)
  const [username, setUsername] = useState<string | null>(null)
  const [staff, setIsStaff] = useState<boolean | null>(false)
  const [loading, setLoading] = useState(true)

  const adopt = useCallback((session: Session) => {
    if (session.access) setAccessToken(session.access)
    setAthlete(session.athlete)
    setUsername(session.user.username)
    const flag = session.user.is_staff ?? session.is_staff
    if (flag !== undefined) {
      setIsStaff(!!flag)
      return
    }
    // Older session payloads don't say: one staff-only read decides (403 → not staff).
    setIsStaff(null)
    api('/admin/ai/providers/').then(() => setIsStaff(true), () => setIsStaff(false))
  }, [])

  // The access token does not survive a reload; the refresh cookie does. Trade it
  // for a new one before deciding the user is logged out.
  // R18 §B: settings can change from memory edits, chat tools or another device —
  // a new data_version re-reads the athlete so every screen sees the effective values.
  const signedIn = !!athlete
  useEffect(() => {
    if (!signedIn) return
    let t: ReturnType<typeof setTimeout> | undefined
    const off = onDataVersionChange(() => {
      clearTimeout(t)
      t = setTimeout(() => { api<Athlete>('/athlete/').then(setAthlete, () => {}) }, 300)
    })
    return () => { clearTimeout(t); off() }
  }, [signedIn])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (await restoreSession()) {
        try {
          const session = await api<Session>('/auth/me/')
          if (!cancelled) adopt(session)
        } catch {
          /* refresh worked but /me did not — treat as logged out */
        }
      }
      if (!cancelled) setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [adopt])

  const value = useMemo<AuthValue>(
    () => ({
      athlete,
      username,
      isStaff: staff === true,
      staffPending: staff === null,
      loading,
      async login(user, password) {
        adopt(await api<Session>('/auth/login/', { method: 'POST', ...json({ username: user, password }) }))
      },
      async register(input) {
        adopt(await api<Session>('/auth/register/', { method: 'POST', ...json(input) }))
      },
      async logout() {
        try {
          await api('/auth/logout/', { method: 'POST' })
        } finally {
          // Clear locally even if the request failed — the cookie is gone either way
          // and leaving stale state on screen is worse than a redundant logout.
          setAccessToken(null)
          setAthlete(null)
          setUsername(null)
          setIsStaff(false)
        }
      },
      async deleteAccount(password) {
        await api('/auth/me/', { method: 'DELETE', ...json({ password }) })
        // The server deleted the user, blacklisted its refresh tokens and cleared the
        // cookie; drop the in-memory session the same way logout does.
        setAccessToken(null)
        setAthlete(null)
        setUsername(null)
        setIsStaff(false)
      },
      async updateAthlete(patch) {
        const updated = await api<Athlete>('/athlete/', { method: 'PATCH', ...json(patch) })
        setAthlete(updated)
        return updated
      },
    }),
    [athlete, username, staff, loading, adopt],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
