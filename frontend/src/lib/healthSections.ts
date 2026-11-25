/**
 * Smooth UI: the Health section chunks, shared by the section routes (pages/Insights)
 * and the warmers in lib/preload. Lives in the Health chunk so the main bundle only
 * carries one import for all of them.
 */
import type { QueryClient } from '@tanstack/react-query'
import { readStored, resolve, type Preset } from '../components/health/healthRange'
import { todayISO } from './format'
import { dayTrendsQuery, healthDayQuery, healthFitnessQuery, healthSleepQuery, insightsQuery } from './queries'

type Loader<T = unknown> = () => Promise<T>

function once<T>(load: Loader<T>): Loader<T> {
  let p: Promise<T> | null = null
  return () => {
    if (!p) {
      p = load()
      p.catch(() => { p = null })
    }
    return p
  }
}

export const sections = {
  day: once(() => import('../components/day/DaySection')),
  dayTrends: once(() => import('../components/day/DayTrendsSection')),
  guides: once(() => import('../components/guides/GuidesSection')),
  habits: once(() => import('../components/habits/HabitsSection')),
  fitness: once(() => import('../components/health/FitnessSection')),
  sleep: once(() => import('../components/health/SleepSection')),
  progress: once(() => import('../components/progress/ProgressSection')),
  more: once(() => import('../components/health/MoreSection')),
  goals: once(() => import('../components/goals/GoalsSection')),
  heart: once(() => import('../components/heart/HeartSection')),
  labs: once(() => import('../components/labs/LabsSection')),
  hr: once(() => import('../components/hr/HeartRateSection')),
  body: once(() => import('../components/weight/BodySection')),
}

const BY_PATH: Record<string, Loader> = {
  day: sections.day, 'day/trends': sections.dayTrends, guides: sections.guides, habits: sections.habits,
  fitness: sections.fitness, sleep: sections.sleep, progress: sections.progress,
  more: sections.more, goals: sections.goals, heart: sections.heart,
  labs: sections.labs, body: sections.body, hr: sections.hr,
}

/** `rest` = the path segments after /health. Overview ships with the Health chunk. */
export function warmSection(rest: string[]): Promise<unknown> {
  const load = BY_PATH[rest.slice(0, 2).join('/')] ?? BY_PATH[rest[0] ?? '']
  return load ? load() : Promise.resolve()
}

/** Each section's main request, for its saved (or default) range. */
const DATA: Record<string, (client: QueryClient, params: (key: string, def: Preset) => string) => Promise<unknown>> = {
  overview: (c, p) => c.prefetchQuery(insightsQuery(p('overview', '4w'))),
  sleep: (c, p) => c.prefetchQuery(healthSleepQuery(p('sleep', '4w'))),
  fitness: (c, p) => Promise.all([c.prefetchQuery(healthFitnessQuery(p('fitness', '6m'))), c.prefetchQuery(insightsQuery('6m'))]),
  day: (c) => Promise.all([c.prefetchQuery(healthDayQuery(todayISO())), c.prefetchQuery(dayTrendsQuery('4w'))]),
}

/**
 * Smooth UI: fetch a section's first screen before it is shown (chip touch-down, and
 * at idle once Health is open), so switching sections lands on content, not skeletons.
 * Fresh cache entries are left alone (staleTime).
 */
export function prefetchSection(client: QueryClient, key: string) {
  const params = (section: string, def: Preset) => resolve(readStored(section) ?? { kind: 'preset', range: def, freq: 'auto' }).params
  void DATA[key]?.(client, params).catch(() => undefined)
}
