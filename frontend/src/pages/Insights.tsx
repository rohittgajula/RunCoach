import { useLayoutEffect } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ChipButton } from '../components/ChipButton'
import { GuidesSection } from '../components/guides/GuidesSection'
import { HabitsPage } from '../components/habits/HabitsSection'
import { GearIcon } from '../components/Icons'
import { OverviewSection } from '../components/insights/OverviewSection'
import { PageHeader } from '../components/PageHeader'
import { ProgressSection } from '../components/progress/ProgressSection'
import { useShell } from '../components/Shell'

const SECTIONS = [
  { to: '/insights', label: 'Overview', end: true },
  { to: '/insights/progress', label: 'Progress', end: false },
  { to: '/insights/habits', label: 'Habits', end: false },
  { to: '/insights/guides', label: 'Guides', end: false },
]

/** Insights: header + sticky Overview · Progress · Habits · Guides, each its own route. */
export default function Insights() {
  const { openSettings } = useShell()
  const { pathname } = useLocation()

  // Each section starts at its top (the Shell only does this per tab).
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  return (
    <div className="page insights-page">
      <div className="insights-top">
        <PageHeader
          title="Insights"
          right={
            <ChipButton label="Settings" onClick={openSettings}>
              <GearIcon />
            </ChipButton>
          }
        />
        <nav className="segmented segmented-full subnav" aria-label="Insights sections">
          {SECTIONS.map((s) => (
            <NavLink
              key={s.to}
              to={s.to}
              end={s.end}
              className={({ isActive }) => `segmented-option ${isActive ? 'is-active' : ''}`}
            >
              {s.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <Routes>
        <Route index element={<OverviewSection />} />
        <Route path="progress" element={<ProgressSection />} />
        <Route path="habits" element={<HabitsPage />} />
        <Route path="guides" element={<GuidesSection />} />
        <Route path="*" element={<Navigate to="/insights" replace />} />
      </Routes>
    </div>
  )
}
