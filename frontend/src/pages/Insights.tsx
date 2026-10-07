import { lazy, Suspense, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { RangeContext, type Preset, type RangeValue } from '../components/health/healthRange'
import { RangePill, RangeSheet, useSectionSelection } from '../components/health/RangeControl'
import { OverviewSection } from '../components/insights/OverviewSection'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/States'

// R13 §16: each Health section is its own chunk; Overview stays with the tab.
const DaySection = lazy(() => import('../components/day/DaySection').then((m) => ({ default: m.DaySection })))
const DayTrendsSection = lazy(() => import('../components/day/DayTrendsSection').then((m) => ({ default: m.DayTrendsSection })))
const GuidesSection = lazy(() => import('../components/guides/GuidesSection').then((m) => ({ default: m.GuidesSection })))
const HabitsPage = lazy(() => import('../components/habits/HabitsSection').then((m) => ({ default: m.HabitsPage })))
const CompareSection = lazy(() => import('../components/health/CompareSection').then((m) => ({ default: m.CompareSection })))
const FitnessSection = lazy(() => import('../components/health/FitnessSection').then((m) => ({ default: m.FitnessSection })))
const ReportsSection = lazy(() => import('../components/health/ReportsSection').then((m) => ({ default: m.ReportsSection })))
const MonthlyReportsPage = lazy(() => import('../components/health/ReportsSection').then((m) => ({ default: m.MonthlyReportsPage })))
const SleepSection = lazy(() => import('../components/health/SleepSection').then((m) => ({ default: m.SleepSection })))
const ProgressSection = lazy(() => import('../components/progress/ProgressSection').then((m) => ({ default: m.ProgressSection })))
// R14: More → Experiments, Goals, Heart (each its own chunk).
const MoreSection = lazy(() => import('../components/health/MoreSection').then((m) => ({ default: m.MoreSection })))
const ExperimentsSection = lazy(() => import('../components/experiments/ExperimentsSection').then((m) => ({ default: m.ExperimentsSection })))
const GoalsSection = lazy(() => import('../components/goals/GoalsSection').then((m) => ({ default: m.GoalsSection })))
const HeartSection = lazy(() => import('../components/heart/HeartSection').then((m) => ({ default: m.HeartSection })))

/**
 * Section chips, in order. `range` = that section's default for the shared range
 * control (none = no range there). Sub-routes (Day trends, Compare) have their own key.
 */
const SECTIONS: Array<{ key: string; to: string; label: string; end?: boolean; range?: Preset; chip?: false; more?: true }> = [
  { key: 'overview', to: '/health', label: 'Overview', end: true, range: '4w' },
  { key: 'day', to: '/health/day', label: 'Day' },
  { key: 'sleep', to: '/health/sleep', label: 'Sleep', range: '4w' },
  { key: 'fitness', to: '/health/fitness', label: 'Fitness', range: '6m' },
  { key: 'habits', to: '/health/habits', label: 'Habits', range: '4w' },
  { key: 'progress', to: '/health/progress', label: 'Progress' },
  { key: 'more', to: '/health/more', label: 'More' },
  { key: 'day/trends', to: '/health/day/trends', label: 'Day trends', range: '4w', chip: false },
  // R14: grouped under More (their chip shows "More" as active).
  { key: 'guides', to: '/health/guides', label: 'Guides', chip: false, more: true },
  { key: 'compare', to: '/health/compare', label: 'Compare', range: '3m', chip: false, more: true },
  { key: 'reports', to: '/health/reports', label: 'Reports', chip: false, more: true },
  { key: 'experiments', to: '/health/experiments', label: 'Experiments', chip: false, more: true },
  { key: 'goals', to: '/health/goals', label: 'Goals', chip: false, more: true },
  { key: 'heart', to: '/health/heart', label: 'Heart', range: '3m', chip: false, more: true },
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
            <NavLink
              key={s.key}
              to={s.to}
              end={s.end}
              className={({ isActive }) => `section-chip ${isActive || (s.key === 'more' && section?.more) ? 'is-active' : ''}`}
            >
              {s.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <RangeContext.Provider value={value}>
        <Suspense fallback={<section className="card"><Skeleton lines={5} /></section>}>
        <Routes>
          <Route index element={<OverviewSection />} />
          <Route path="day" element={<DaySection />} />
          <Route path="day/trends" element={<DayTrendsSection />} />
          <Route path="fitness" element={<FitnessSection />} />
          <Route path="sleep" element={<SleepSection />} />
          <Route path="habits" element={<HabitsPage />} />
          <Route path="progress" element={<ProgressSection />} />
          <Route path="guides" element={<GuidesSection />} />
          <Route path="more" element={<MoreSection />} />
          <Route path="experiments" element={<ExperimentsSection />} />
          <Route path="goals" element={<GoalsSection />} />
          <Route path="heart" element={<HeartSection />} />
          <Route path="compare" element={<CompareSection />} />
          <Route path="reports" element={<ReportsSection />} />
          <Route path="reports/monthly" element={<MonthlyReportsPage />} />
          <Route path="reports/monthly/:month" element={<MonthlyReportsPage />} />
          <Route path="reports/:week" element={<ReportsSection />} />
          <Route path="*" element={<Navigate to="/health" replace />} />
        </Routes>
        </Suspense>
      </RangeContext.Provider>
      <RangeSheet open={sheet && !!key} onClose={() => setSheet(false)} period={period} onApply={setSelection} title={section ? `${section.label} range` : 'Range'} />
    </div>
  )
}
