import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { CalendarIcon, ChatIcon, DietIcon, InsightsIcon, ProfileIcon } from './Icons'
import { SettingsSheet } from './SettingsSheet'

const TABS = [
  { to: '/calendar', label: 'Calendar', Icon: CalendarIcon },
  { to: '/chat', label: 'Chat', Icon: ChatIcon },
  { to: '/diet', label: 'Diet', Icon: DietIcon },
  { to: '/insights', label: 'Insights', Icon: InsightsIcon },
  { to: '/profile', label: 'Profile', Icon: ProfileIcon },
]

type ShellValue = { openSettings: () => void }
const ShellContext = createContext<ShellValue>({ openSettings: () => {} })
export const useShell = () => useContext(ShellContext)

/** Five tabs, nothing else. Pages own their header and scroll container. */
export function Shell({ children }: { children: ReactNode }) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const openSettings = useCallback(() => setSettingsOpen(true), [])
  const value = useMemo(() => ({ openSettings }), [openSettings])
  const { pathname } = useLocation()

  // Each tab starts at its own top. A layout effect, so it runs before any page's own
  // effect — Calendar scrolls itself to today afterwards and must win.
  const tab = pathname.split('/')[1]
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [tab])

  return (
    <ShellContext.Provider value={value}>
      <div className="app">
        <main className="shell-main">{children}</main>
        <nav className="tabbar" aria-label="Main">
          {TABS.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `tab ${isActive ? 'is-active' : ''}`}>
              <span className="tab-icon">
                <Icon size={24} />
              </span>
              <span className="tab-label">{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
      <SettingsSheet open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </ShellContext.Provider>
  )
}
