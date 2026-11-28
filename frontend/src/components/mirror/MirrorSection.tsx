/**
 * The weekly mirror: what you said you would do, against what you did.
 *
 * Everything on this screen exists elsewhere in the app — runs have a compliance
 * score, food has targets and a log, sleep and water have both. What has never
 * existed is the two columns next to each other, so a week where the running held
 * and the eating fell apart reads as that, rather than as two screens that each
 * look fine on their own.
 *
 * It does not encourage. There is no "good week", no streak, no goal for next
 * week — the weekly report already does that, and a mirror that editorialises
 * stops being a mirror. The headline counts ("3 of 5 on target") because a count
 * is something you can argue with.
 *
 * The one thing it must never do is read a missing log as a zero. Not logging
 * dinner is not eating nothing, and a row scored that way is discouraging about
 * something that did not happen. So a row without enough days says how many it
 * has and shows no number, a row whose target cannot be computed names the empty
 * Settings field instead of blaming him, and neither counts as a miss.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { CardHead } from '../Kit'
import { ErrorState, Skeleton } from '../States'

type Status = 'hit' | 'under' | 'over' | 'not_enough_data' | 'nothing_planned' | 'no_target'

type Row = {
  key: string; label: string
  planned: number | null; done: number | null
  unit: string; status: Status
  gap: number | null; pct: number | null
  note: string; days: number; of_days: number
  bad: 'under' | 'over' | 'both' | 'neither'
  /** True only for rows read from a log. A Runs row is not "logged on n days". */
  needs_days: boolean
}
type Body = {
  week_start: string; week_end: string
  in_progress: boolean; elapsed_days: number
  headline: string; missed: number; judged: number; worst: string | null
  rows: Row[]
}

/** Only a real miss gets a colour. Absence is grey, never red. */
const TONE: Record<Status, string> = {
  hit: 'is-hit',
  under: 'is-miss',
  over: 'is-miss',
  not_enough_data: 'is-quiet',
  nothing_planned: 'is-quiet',
  no_target: 'is-quiet',
}

const JUDGED: Status[] = ['hit', 'under', 'over']

function num(value: number | null, unit: string): string {
  if (value === null) return '—'
  // Hours come through as 7.5; everything else is already whole.
  const shown = Number.isInteger(value) ? value : value.toFixed(1)
  return `${shown}${unit === 'h' ? ' h' : ''}`
}

export function MirrorSection() {
  // 0 = this week, 1 = last week, and so on. Weeks back rather than a date picker:
  // the question is almost always "this week" or "last week".
  const [back, setBack] = useState(0)
  const week = weekStart(back)
  const q = useQuery<Body>({
    queryKey: ['mirror', week],
    queryFn: () => api<Body>(`/health/mirror/?week=${week}`),
  })

  if (q.isLoading) return <Skeleton lines={7} />
  if (q.error) return <ErrorState message={errorText(q.error)} onRetry={() => q.refetch()} />
  const body = q.data
  if (!body) return null

  return (
    <div className="stack">
      <section className="card stack">
        <CardHead
          title="Planned vs done"
          sub={`${body.week_start} to ${body.week_end}${
            body.in_progress ? ` · ${body.elapsed_days} days in so far` : ''
          }`}
          aside={
            <div className="mirror-nav">
              <button type="button" className="btn btn-ghost btn-sm"
                      onClick={() => setBack((b) => b + 1)}>Earlier</button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={back === 0}
                      onClick={() => setBack((b) => Math.max(0, b - 1))}>Later</button>
            </div>
          }
        />
        <p className="mirror-headline">{body.headline}</p>
        {body.in_progress && (
          <p className="muted small">
            The week is not over, so anything planned for the days still to come is not
            counted as missed.
          </p>
        )}

        <ul className="mirror-rows">
          {body.rows.map((r) => {
            const judged = JUDGED.includes(r.status)
            return (
              <li key={r.key} className={`mirror-row ${TONE[r.status]}${
                r.key === body.worst ? ' is-worst' : ''}`}>
                <div className="mirror-row-top">
                  <span className="mirror-label">{r.label}</span>
                  {judged && (
                    <span className="mirror-pair">
                      <span className="num">{num(r.done, r.unit)}</span>
                      <span className="mirror-of">of {num(r.planned, r.unit)}</span>
                    </span>
                  )}
                </div>
                {judged && r.pct !== null && (
                  <div className="mirror-bar" role="img"
                       aria-label={`${r.pct}% of target`}>
                    {/* Capped at 100% of the track so a 200% row does not spill;
                        the number beside it still says 200. */}
                    <span className="mirror-fill" style={{ width: `${Math.min(r.pct, 100)}%` }} />
                  </div>
                )}
                <p className="mirror-note">
                  {r.note}
                  {judged && r.needs_days && r.days < r.of_days && (
                    <span className="muted"> ({r.days} of {r.of_days} days logged)</span>
                  )}
                </p>
              </li>
            )
          })}
        </ul>
      </section>

      <p className="muted small">
        Runs and strength come from your plan, food from what you logged against that
        day’s target, sleep from your watch, water from the water log. Nothing here is
        computed twice — every row is the same number its own screen shows.
      </p>
    </div>
  )
}

/** The Monday `back` weeks ago, in local time. */
function weekStart(back: number): string {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  const monday = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - monday - back * 7)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
