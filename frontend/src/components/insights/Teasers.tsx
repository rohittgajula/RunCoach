import { Link } from 'react-router-dom'
import { ApiError } from '../../lib/auth'
import { useHabitSummary, useHabitsToday, useProgress } from '../../lib/queries'
import type { ProgressMetric } from '../../lib/types'
import { HABITS } from '../habits/habitUtil'
import { ChevronRight } from '../Icons'

const notDeployed = (error: unknown) => error instanceof ApiError && error.status === 404

function Teaser({ to, title, text }: { to: string; title: string; text: string }) {
  return (
    <Link to={to} className="card teaser">
      <div className="grow">
        <p className="teaser-title">{title}</p>
        <p className="teaser-text">{text}</p>
      </div>
      <ChevronRight size={20} />
    </Link>
  )
}

const paceChange = (m: ProgressMetric | undefined) => {
  if (!m || m.delta == null || Math.round(m.delta) === 0) return null
  const s = Math.abs(Math.round(m.delta))
  return `pace ${s} s/km ${m.delta < 0 ? 'faster' : 'slower'}`
}
const hrChange = (m: ProgressMetric | undefined) => {
  if (!m || m.delta == null || Math.round(m.delta) === 0) return null
  return `HR ${m.delta > 0 ? '+' : '−'}${Math.abs(Math.round(m.delta))} bpm`
}

/** "Last 5 runs: pace 6 s/km faster · HR −3 bpm ›" */
export function ProgressTeaser() {
  const progress = useProgress({ window: 5 })
  if (progress.isError && notDeployed(progress.error)) return null
  const metrics = progress.data?.metrics ?? []
  const find = (key: string) => metrics.find((m) => m.key === key)
  const parts = [paceChange(find('run_pace')), hrChange(find('avg_hr'))].filter(Boolean)
  const runs = progress.data?.current_n ?? progress.data?.period?.runs_current
  const text = progress.isPending
    ? 'Comparing your recent runs…'
    : parts.length
      ? `Last 5 runs: ${parts.join(' · ')}`
      : runs
        ? 'Last 5 runs: about the same as the 5 before'
        : 'Compare your recent runs with the ones before'
  return <Teaser to="/insights/progress" title="Progress" text={text} />
}

/** Smoke-free streak or today's counts (never 🌙). */
export function HabitsTeaser() {
  const today = useHabitsToday()
  const summary = useHabitSummary('4w')
  if (today.isError && notDeployed(today.error)) return null
  const streak = summary.data?.smoke.streak
  const counts = today.data?.counts
  const logged = HABITS.filter((h) => (counts?.[h.kind] ?? 0) > 0)
  const parts: string[] = []
  if (streak && streak.current_days > 0 && ((summary.data?.smoke.total ?? 0) > 0 || streak.best_days > 0)) {
    parts.push(`🚬 ${streak.current_days} ${streak.current_days === 1 ? 'day' : 'days'} smoke-free`)
  }
  if (logged.length) parts.push(`Today ${logged.map((h) => `${h.emoji} ${counts?.[h.kind]}`).join(' · ')}`)
  const text = parts.length ? parts.join(' · ') : 'Health report, trends and how habits affect your runs'
  return <Teaser to="/insights/habits" title="Habits" text={text} />
}
