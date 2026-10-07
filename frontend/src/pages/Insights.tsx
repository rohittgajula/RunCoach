import { useLayoutEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { DaySection } from '../components/day/DaySection'
import { DayTrendsSection } from '../components/day/DayTrendsSection'
import { GuidesSection } from '../components/guides/GuidesSection'
import { HabitsPage } from '../components/habits/HabitsSection'
import { CompareSection } from '../components/health/CompareSection'
import { RangeContext, type RangeValue } from '../components/health/healthRange'
import { FitnessSection } from '../components/health/FitnessSection'
import { ReportsSection } from '../components/health/ReportsSection'
import { SleepSection } from '../components/health/SleepSection'
import { OverviewSection } from '../components/insights/OverviewSection'
import { PageHeader } from '../components/PageHeader'
import { ProgressSection } from '../components/progress/ProgressSection'
import { RangeSwitch } from '../components/RangeSwitch'

type Option = { value: string; label: string }

const INSIGHT: Option[] = [
  { value: '4w', label: '4w' },
  { value: '12w', label: '12w' },
  { value: '6m', label: '6m' },
]
const SHORT: Option[] = [
  { value: '7d', label: '7d' },
  { value: '4w', label: '4w' },
  { value: '3m', label: '3m' },
]
const LONG: Option[] = [
  { value: '3m', label: '3m' },
  { value: '6m', label: '6m' },
  { value: '1y', label: '1y' },
]

/** Section chips, in order. `range` = the header switch for that section (none = hidden). */
const SECTIONS: Array<{ key: string; to: string; label: string; end?: boolean; range?: Option[]; initial?: string }> = [
  { key: 'overview', to: '/health', label: 'Overview', end: true, range: INSIGHT, initial: '4w' },
  { key: 'day', to: '/health/day', label: 'Day' },
  { key: 'fitness', to: '/health/fitness', label: 'Fitness', range: LONG, initial: '6m' },
  { key: 'sleep', to: '/health/sleep', label: 'Sleep', range: SHORT, initial: '4w' },
  { key: 'habits', to: '/health/habits', label: 'Habits', range: INSIGHT, initial: '4w' },
  { key: 'progress', to: '/health/progress', label: 'Progress' },
  { key: 'guides', to: '/health/guides', label: 'Guides' },
]


function sectionOf(pathname: string) {
  const part = pathname.split('/')[2] ?? ''
  return SECTIONS.find((s) => s.key === part) ?? (part ? null : SECTIONS[0])
}

/** Health: header + range, swipeable section chips, each section its own route. */
export default function Health() {
  const { pathname } = useLocation()
  const section = sectionOf(pathname)
  const [ranges, setRanges] = useState<Record<string, string>>(() =>
    Object.fromEntries(SECTIONS.filter((s) => s.initial).map((s) => [s.key, s.initial!])))
  const chips = useRef<HTMLElement>(null)

  // Each section starts at its top (the Shell only does this per tab).
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
    // Keep the active chip in view on narrow phones.
    chips.current?.querySelector<HTMLElement>('.is-active')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [pathname])

  const key = section?.key ?? ''
  const value: RangeValue = {
    range: ranges[key] ?? section?.initial ?? '4w',
    setRange: (r) => setRanges((prev) => ({ ...prev, [key]: r })),
  }

  return (
    <div className="page health-page">
      <div className="health-top">
        <PageHeader
          title="Health"
          right={section?.range && <RangeSwitch compact value={value.range} onChange={value.setRange} options={section.range} />}
        />
        <nav className="section-chips" aria-label="Health sections" ref={chips}>
          {SECTIONS.map((s) => (
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
    </div>
  )
}
