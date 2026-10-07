import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { DaySection } from '../components/day/DaySection'
import { DayTrendsSection } from '../components/day/DayTrendsSection'
import { GuidesSection } from '../components/guides/GuidesSection'
import { HabitsPage } from '../components/habits/HabitsSection'
import { CompareSection } from '../components/health/CompareSection'
import { RangeContext, type Preset, type RangeValue } from '../components/health/healthRange'
import { RangePill, RangeSheet, useSectionSelection } from '../components/health/RangeControl'
import { FitnessSection } from '../components/health/FitnessSection'
import { ReportsSection } from '../components/health/ReportsSection'
import { SleepSection } from '../components/health/SleepSection'
import { OverviewSection } from '../components/insights/OverviewSection'
import { PageHeader } from '../components/PageHeader'
import { ProgressSection } from '../components/progress/ProgressSection'

/**
 * Section chips, in order. `range` = that section's default for the shared range
 * control (none = no range there). Sub-routes (Day trends, Compare) have their own key.
 */
const SECTIONS: Array<{ key: string; to: string; label: string; end?: boolean; range?: Preset; chip?: false }> = [
  { key: 'overview', to: '/health', label: 'Overview', end: true, range: '4w' },
  { key: 'day', to: '/health/day', label: 'Day' },
  { key: 'fitness', to: '/health/fitness', label: 'Fitness', range: '6m' },
  { key: 'sleep', to: '/health/sleep', label: 'Sleep', range: '4w' },
  { key: 'habits', to: '/health/habits', label: 'Habits', range: '4w' },
  { key: 'progress', to: '/health/progress', label: 'Progress' },
  { key: 'guides', to: '/health/guides', label: 'Guides' },
  { key: 'day/trends', to: '/health/day/trends', label: 'Day trends', range: '4w', chip: false },
  { key: 'compare', to: '/health/compare', label: 'Compare', range: '3m', chip: false },
]

function sectionOf(pathname: string) {
  const parts = pathname.split('/').slice(2).filter(Boolean)
  const two = parts.slice(0, 2).join('/')
  return SECTIONS.find((s) => s.key === two) ?? SECTIONS.find((s) => s.key === (parts[0] ?? '')) ?? (parts.length ? null : SECTIONS[0])
}

/** Health: header + range, swipeable section chips, each section its own route. */
export default function Health() {
  const { pathname } = useLocation()
  const section = sectionOf(pathname)
  const key = section?.range ? section.key : ''
  const [period, setSelection] = useSectionSelection(key, section?.range ?? '4w')
  const [sheet, setSheet] = useState(false)
  const chips = useRef<HTMLElement>(null)

  // Each section starts at its top (the Shell only does this per tab).
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
    // Keep the active chip in view on narrow phones.
    chips.current?.querySelector<HTMLElement>('.is-active')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [pathname])

  const value = useMemo<RangeValue>(
    () => ({ section: key, period, setSelection, openSheet: () => setSheet(true) }),
    [key, period, setSelection],
  )

  return (
    <div className="page health-page">
      <div className="health-top">
        <PageHeader
          title="Health"
          right={key ? <RangePill period={period} onClick={() => setSheet(true)} /> : undefined}
        />
        <nav className="section-chips" aria-label="Health sections" ref={chips}>
          {SECTIONS.filter((s) => s.chip !== false).map((s) => (
            <NavLink key={s.key} to={s.to} end={s.end} className={({ isActive }) => `section-chip ${isActive ? 'is-active' : ''}`}>
              {s.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <RangeContext.Provider value={value}>
        <Routes>
          <Route index element={<OverviewSection />} />
          <Route path="day" element={<DaySection />} />
          <Route path="day/trends" element={<DayTrendsSection />} />
          <Route path="fitness" element={<FitnessSection />} />
          <Route path="sleep" element={<SleepSection />} />
          <Route path="habits" element={<HabitsPage />} />
          <Route path="progress" element={<ProgressSection />} />
          <Route path="guides" element={<GuidesSection />} />
          <Route path="compare" element={<CompareSection />} />
          <Route path="reports" element={<ReportsSection />} />
          <Route path="reports/:week" element={<ReportsSection />} />
          <Route path="*" element={<Navigate to="/health" replace />} />
        </Routes>
      </RangeContext.Provider>
      <RangeSheet open={sheet && !!key} onClose={() => setSheet(false)} period={period} onApply={setSelection} title={section ? `${section.label} range` : 'Range'} />
    </div>
  )
}
