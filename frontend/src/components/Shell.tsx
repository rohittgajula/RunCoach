import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { intentHandlers, isPlainClick, navigateSmooth, reducedMotion, routeCommitted } from '../lib/navMotion'
import { prefetchHealth, preloadTabs, whenIdle } from '../lib/preload'
import { prefetchTab } from '../lib/queries'
import { SyncingPill, useAutoSync } from '../lib/r16'
import { UpdateBanner } from '../lib/r18'
import { useAuth } from '../lib/AuthContext'
import { CoachIcon, DietIcon, HealthIcon, ListIcon, PlanIcon, TodayIcon } from './Icons'
import { BadgeToast } from './me/Badges'
import { GlobalToast } from './GlobalToast'
import { SettingsSheet } from './SettingsSheet'

const TABS = [
  { to: '/today', label: 'Today', Icon: TodayIcon },
  { to: '/plan', label: 'Plan', Icon: PlanIcon },
  { to: '/health', label: 'Health', Icon: HealthIcon },
  // Fifth tab: logging a meal is a several-times-a-day action, and it was
  // two taps and a sideways chip scroll inside Health. The bar was already
  // sized for six at 375px.
  { to: '/diet', label: 'Food', Icon: DietIcon },
  // "Runs", not "Activities": shorter, and in a running app it is also the more
  // direct word. The short label is what makes six tabs fit a 375px phone at
  // all — the first version hid this tab on mobile entirely, which put the list
  // of your own runs behind a desktop.
  { to: '/activities', label: 'Runs', Icon: ListIcon },
]

type ShellValue = { openSettings: (focus?: unknown) => void }
const ShellContext = createContext<ShellValue>({ openSettings: () => {} })
export const useShell = () => useContext(ShellContext)

/** Four tabs — Today · Plan · Runs · Health — and the coach as a bubble.
 *
 * Six tabs on a 375px phone was about 62px each and read as congested. Coach is
 * the one that leaves most willingly: it is not a place you browse, it is a
 * thing you start, and a floating button says that better than a tab does. It
 * also sits above whatever you were looking at, so you can ask about the screen
 * you are on rather than leaving it first.
 *
 * Diet held this slot and came out: the app had drifted away from the one job
 * Rohit uses it for. Gym took it next and came out for the same reason — a
 * whole tab for two sessions a week, against ten runs in eleven weeks, is the
 * app asking for attention it has not earned. Strength is now a day on the
 * calendar like any other, which is what it always was.
 *
 * Both redirect rather than 404, so an old bookmark or an installed PWA
 * shortcut still lands somewhere sensible, and neither deletion touched the
 * backend: gym sessions are still planned, still pushed to the watch, still
 * counted as a workout on the day they fall on.
 */
export function Shell({ children }: { children: ReactNode }) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  // R14: a settings group to open (and scroll to) straight away, e.g. "today".
  const [focus, setFocus] = useState<string | undefined>()
  const openSettings = useCallback((f?: unknown) => {
    setFocus(typeof f === 'string' ? f : undefined)
    setSettingsOpen(true)
  }, [])
  const value = useMemo(() => ({ openSettings }), [openSettings])
  const location = useLocation()
  const { pathname } = location
  const navigate = useNavigate()
  const tab = pathname.split('/')[1]
  // A link inside Settings (R18: "from your memory note") leaves the sheet behind.
  useEffect(() => { setSettingsOpen(false) }, [pathname])
  // R16 §C: sync Garmin on open / focus when the server says it's due.
  const { athlete } = useAuth()
  useAutoSync(!!athlete?.garmin_connected)

  // Smooth UI: warm every tab and Health section once the first screen has painted,
  // whichever screen that is (a deep link to /health needs it as much as Today).
  // Then the first screen of Plan, Coach, Diet and Health, so a first visit opens on content.
  const client = useQueryClient()
  useEffect(() => {
    preloadTabs()
    const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData
    if (saveData) return
    let tries = 0
    const run = () => {
      // Let the screen on show finish its own requests first.
      if (client.isFetching() > 0 && tries++ < 5) return void setTimeout(() => whenIdle(run, 3000), 800)
      // '/diet' was in this list after the route stopped existing — a warm-up
      // for a page nobody can reach. '/chat' stays: the bubble opens it.
      for (const to of ['/plan', '/chat', '/activities']) prefetchTab(client, to)
      prefetchHealth(client)
    }
    whenIdle(run, 6000)
  }, [client])

  // The tapped tab lights up on the tap itself, not when the next screen has rendered
  // (the router commits inside a transition, so `isActive` lags on a slow phone).
  const [pending, setPending] = useState<string | null>(null)
  useEffect(() => {
    if (!pending) return
    const timer = setTimeout(() => setPending(null), 1500)
    return () => clearTimeout(timer)
  }, [pending])

  // Each tab keeps its own scroll position, the way native tab bars do. A layout
  // effect, so it lands before paint (and before a View Transition snapshot); pages
  // with their own scroller (Plan, Coach) scroll themselves afterwards and win.
  const scrolls = useRef(new Map<string, number>())
  const tabRef = useRef(tab)
  useEffect(() => {
    // Recorded on scroll, and again on whatever starts a navigation (a tap, the back
    // button) while the old screen is still in the DOM — a fling's last scroll event
    // can arrive after the switch.
    const save = () => { scrolls.current.set(tabRef.current, window.scrollY) }
    window.addEventListener('scroll', save, { passive: true })
    document.addEventListener('click', save, true)
    window.addEventListener('popstate', save, true)
    return () => {
      window.removeEventListener('scroll', save)
      document.removeEventListener('click', save, true)
      window.removeEventListener('popstate', save, true)
    }
  }, [])
  useLayoutEffect(() => {
    tabRef.current = tab
    window.scrollTo(0, scrolls.current.get(tab) ?? 0)
  }, [tab])

  useLayoutEffect(() => {
    setPending(null)
    routeCommitted()
  }, [location.key])

  const tabIndex = TABS.findIndex((t) => t.to.slice(1) === tab)
  const onTab = (event: MouseEvent, to: string, index: number) => {
    if (!isPlainClick(event)) return
    event.preventDefault()
    // Tapping the tab you are on goes back to its top (and its root screen).
    if (pathname === to) {
      window.scrollTo({ top: 0, behavior: reducedMotion() ? 'auto' : 'smooth' })
      return
    }
    setPending(to)
    navigateSmooth(navigate, to, tabIndex < 0 || index === tabIndex ? 'fade' : index > tabIndex ? 'fwd' : 'back')
  }

  return (
    <ShellContext.Provider value={value}>
      <div className="app">
        <main className="shell-main">{children}</main>
        <nav className="tabbar" aria-label="Main">
          {TABS.map(({ to, label, Icon }, index) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `tab ${(pending ? pending === to : isActive) ? 'is-active' : ''}`}
              onClick={(event) => onTab(event, to, index)}
              {...intentHandlers(to)}
              onPointerDown={() => {
                intentHandlers(to).onPointerDown()
                if (to === '/health') prefetchHealth(client)
                else prefetchTab(client, to)
              }}
            >
              <span className="tab-icon">
                <Icon size={24} />
              </span>
              <span className="tab-label">{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* The coach, as a bubble rather than a tab.
       *
       * It sits above whatever you are looking at, which is the point: a
       * question about this week's plan is best asked from the plan, not after
       * navigating away from it. Hidden on the coach's own screens, where a
       * button that takes you where you already are is just clutter.
       *
       * Hidden on a run's own page too, for two reasons. It sat over the
       * right-hand axis labels of the pace, heart-rate, cadence and elevation
       * charts — it is a 54px circle in the bottom-right corner and those
       * labels are 30 to 74px in from that edge, so the numbers at the bottom
       * of the screen were unreadable while scrolling. And that screen already
       * has a better door to the coach than a floating circle: "What the coach
       * makes of it", which arrives with the run already in hand. */}
      {!location.pathname.startsWith('/chat')
        && !/^\/activities\/\d/.test(location.pathname) && (
        <NavLink
          to="/chat"
          className="coach-fab"
          aria-label="Ask the coach"
          {...intentHandlers('/chat')}
          onPointerDown={() => {
            intentHandlers('/chat').onPointerDown()
            prefetchTab(client, '/chat')
          }}
        >
          <CoachIcon size={24} />
        </NavLink>
      )}

      {tab !== 'today' && <div className="sync-float"><SyncingPill /></div>}
      <UpdateBanner />
      <BadgeToast />
      <GlobalToast />
      <SettingsSheet open={settingsOpen} focus={focus} onClose={() => setSettingsOpen(false)} />
    </ShellContext.Provider>
  )
}
