import { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { RangeContext, type Preset, type RangeValue } from '../components/health/healthRange'
import { RangePill, RangeSheet, useSectionSelection } from '../components/health/RangeControl'
import { OverviewSection } from '../components/insights/OverviewSection'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/States'
import { intentHandlers, isPlainClick, navigateSmooth } from '../lib/navMotion'
import { prefetchSection, sections } from '../lib/healthSections'
import { PullToRefresh, RefreshButton } from '../lib/r18'
import { whenIdle } from '../lib/preload'

// R13 §16: each Health section is its own chunk; Overview stays with the tab. The
// loaders live in lib/healthSections so idle/touch warming and the route share one promise.
const DaySection = lazy(() => sections.day().then((m) => ({ default: m.DaySection })))
const DayTrendsSection = lazy(() => sections.dayTrends().then((m) => ({ default: m.DayTrendsSection })))
const GuidesSection = lazy(() => sections.guides().then((m) => ({ default: m.GuidesSection })))
const HabitsPage = lazy(() => sections.habits().then((m) => ({ default: m.HabitsPage })))
const FitnessSection = lazy(() => sections.fitness().then((m) => ({ default: m.FitnessSection })))
const SleepSection = lazy(() => sections.sleep().then((m) => ({ default: m.SleepSection })))
const ProgressSection = lazy(() => sections.progress().then((m) => ({ default: m.ProgressSection })))
// R14: More → Experiments, Goals, Heart (each its own chunk).
const MoreSection = lazy(() => sections.more().then((m) => ({ default: m.MoreSection })))
const GoalsSection = lazy(() => sections.goals().then((m) => ({ default: m.GoalsSection })))
const HeartSection = lazy(() => sections.heart().then((m) => ({ default: m.HeartSection })))
const LabsSection = lazy(() => sections.labs().then((m) => ({ default: m.LabsSection })))
const BodySection = lazy(() => sections.body().then((m) => ({ default: m.BodySection })))
const HeartRateSection = lazy(() => sections.hr().then((m) => ({ default: m.HeartRateSection })))

/**
 * Section chips, in order. `range` = that section's default for the shared range
 * control (none = no range there). Sub-routes (Day trends, Compare) have their own key.
 */
const SECTIONS: Array<{ key: string; to: string; label: string; end?: boolean; range?: Preset; chip?: false; more?: true }> = [
  // R24: Rohit's own order. Heart rate sits early because it is the thing he
  // checks; Heart (heart rate against pace) follows Fitness because it only
  // means anything once you have been running a while.
  { key: 'overview', to: '/health', label: 'Overview', end: true, range: '4w' },
  { key: 'day', to: '/health/day', label: 'Day' },
  { key: 'sleep', to: '/health/sleep', label: 'Sleep', range: '4w' },
  { key: 'hr', to: '/health/hr', label: 'Heart rate', range: '4w' },
  { key: 'fitness', to: '/health/fitness', label: 'Fitness', range: '6m' },
  { key: 'heart', to: '/health/heart', label: 'Heart', range: '3m' },
  { key: 'progress', to: '/health/progress', label: 'Progress' },
  { key: 'habits', to: '/health/habits', label: 'Habits', range: '4w' },
  { key: 'more', to: '/health/more', label: 'More' },
  { key: 'day/trends', to: '/health/day/trends', label: 'Day trends', range: '4w', chip: false },
  // R14: grouped under More (their chip shows "More" as active).
  { key: 'guides', to: '/health/guides', label: 'Guides', chip: false, more: true },
  { key: 'goals', to: '/health/goals', label: 'Goals', chip: false, more: true },
  { key: 'body', to: '/health/body', label: 'Weight', chip: false, more: true },
  { key: 'labs', to: '/health/labs', label: 'Blood & urine', chip: false, more: true },
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
  const navigate = useNavigate()
  // Smooth UI: the tapped chip lights up at once; the section follows in a transition.
  const [pending, setPending] = useState<string | null>(null)
  useEffect(() => { setPending(null) }, [pathname])
  // …and lands on content: the main sections' data is fetched once Health is idle, and
  // again (if stale) on the finger touching a chip.
  const client = useQueryClient()
  useEffect(() => {
    whenIdle(() => { for (const k of ['overview', 'sleep', 'fitness', 'day']) prefetchSection(client, k) }, 3000)
  }, [client])
  const chipList = SECTIONS.filter((s) => s.chip !== false)
  const chipIndex = (key?: string) => chipList.findIndex((c) => c.key === key)
  const current = section?.more ? chipIndex('more') : chipIndex(section?.key === 'day/trends' ? 'day' : section?.key)
  const onChip = (event: MouseEvent, to: string, index: number) => {
    if (!isPlainClick(event)) return
    event.preventDefault()
    if (pathname === to) return
    setPending(to)
    navigateSmooth(navigate, to, current < 0 || index === current ? 'fade' : index > current ? 'fwd' : 'back')
  }

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
          right={<span className="health-head-right">{key && <RangePill period={period} onClick={() => setSheet(true)} />}<RefreshButton /></span>}
        />
        <PullToRefresh />
        <nav className="section-chips" aria-label="Health sections" ref={chips}>
          {chipList.map((s, index) => (
            <NavLink
              key={s.key}
              to={s.to}
              end={s.end}
              className={({ isActive }) => `section-chip ${(pending ? pending === s.to : isActive || (s.key === 'more' && section?.more)) ? 'is-active' : ''}`}
              onClick={(event) => onChip(event, s.to, index)}
              {...intentHandlers(s.to)}
              onPointerDown={() => { intentHandlers(s.to).onPointerDown(); prefetchSection(client, s.key) }}
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
          <Route path="goals" element={<GoalsSection />} />
          <Route path="heart" element={<HeartSection />} />
          <Route path="hr" element={<HeartRateSection />} />
          <Route path="body" element={<BodySection />} />
          <Route path="labs" element={<LabsSection />} />
          <Route path="*" element={<Navigate to="/health" replace />} />
        </Routes>
        </Suspense>
      </RangeContext.Provider>
      <RangeSheet open={sheet && !!key} onClose={() => setSheet(false)} period={period} onApply={setSelection} title={section ? `${section.label} range` : 'Range'} />
    </div>
  )
}
