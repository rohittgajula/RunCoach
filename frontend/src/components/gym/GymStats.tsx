/**
 * What the gym has actually amounted to.
 *
 * The Gym tab showed the next session and the ladders, and nothing at all
 * about whether any of it was happening. That is the one question strength
 * training turns on: it works through repetition over months, so "did I turn
 * up" matters more than any single session did.
 *
 * Two things here. How many sessions landed each week, which is the honest
 * compliance picture — and where each movement stands on its ladder, which is
 * the only progress a beginner can see, because the weight never changes.
 *
 * The window is eight weeks: long enough to show a habit forming or not, and
 * inside the endpoint's 62-day cap.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { addDays, todayISO } from '../../lib/format'

const WEEKS = 8

type Session = { id: number; date: string; status: string }
type Payload = { sessions: Session[]; levels: Record<string, number> }

const PATTERNS: [string, string][] = [
  ['calf', 'Calf'], ['squat', 'Squat'], ['hinge', 'Hinge'],
  ['push', 'Push'], ['pull', 'Pull'], ['core', 'Core'],
]

/** Monday of the week a date falls in. */
function monday(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  const back = (d.getDay() + 6) % 7
  return addDays(iso, -back)
}

export function GymStats({ ceilings }: { ceilings: Record<string, number> }) {
  const today = todayISO()
  const start = monday(addDays(today, -7 * (WEEKS - 1)))
  const end = today

  const query = useQuery<Payload>({
    queryKey: ['strength', 'history', start],
    queryFn: () => api(`/strength/?start=${start}&end=${end}`),
    staleTime: 5 * 60_000,
  })

  if (query.isPending || query.isError || !query.data) return null

  const sessions = query.data.sessions ?? []
  const levels = query.data.levels ?? {}

  const weeks = Array.from({ length: WEEKS }, (_, i) => {
    const weekStart = addDays(start, i * 7)
    const inWeek = sessions.filter((s) => monday(s.date) === weekStart)
    return {
      start: weekStart,
      planned: inWeek.length,
      done: inWeek.filter((s) => s.status === 'completed').length,
    }
  })

  const done = weeks.reduce((n, w) => n + w.done, 0)
  const planned = weeks.reduce((n, w) => n + w.planned, 0)
  const mostInAWeek = Math.max(1, ...weeks.map((w) => w.planned))

  return (
    <section className="card stack gymstats">
      <div className="row">
        <strong>Your gym so far</strong>
        <span className="muted small num">{done} of {planned} in {WEEKS} weeks</span>
      </div>

      <div className="gymstats-bars" role="img"
        aria-label={`${done} of ${planned} sessions done over ${WEEKS} weeks`}>
        {weeks.map((w) => (
          <div className="gymstats-week" key={w.start}>
            <div className="gymstats-stack">
              {Array.from({ length: mostInAWeek }, (_, i) => {
                const state = i < w.done ? 'done' : i < w.planned ? 'missed' : 'none'
                return <i key={i} data-state={state} />
              }).reverse()}
            </div>
            <span className="gymstats-dow">{new Date(`${w.start}T00:00:00`).getDate()}</span>
          </div>
        ))}
      </div>
      <p className="muted small gymstats-key">
        Filled is a session you did; hollow is one that was planned and did not
        happen.
      </p>

      <div className="row" style={{ marginTop: 4 }}>
        <strong>Where each movement stands</strong>
      </div>
      <ul className="gymstats-rungs">
        {PATTERNS.map(([key, label]) => {
          const level = levels[key] ?? 1
          const ceiling = ceilings[key] ?? 5
          return (
            <li key={key}>
              <span className="gymstats-pattern">{label}</span>
              <span className="rungs" aria-label={`Rung ${level} of ${ceiling}`}>
                {Array.from({ length: 5 }, (_, i) => {
                  const rung = i + 1
                  const state = rung <= level ? 'on' : rung <= ceiling ? '' : 'locked'
                  return <i key={rung} className={state} />
                })}
              </span>
              <span className="gymstats-rung num">{level}/{ceiling}</span>
            </li>
          )
        })}
      </ul>
      <p className="muted small">
        A bar that stops short because the ladder ran out and one that stops
        because there is no dumbbell in the room are different things — the
        locked rungs are the second kind.
      </p>
    </section>
  )
}
