/**
 * "Is this the same knee again?"
 *
 * Pain has been logged per day since R13 — spot, side, severity — and the only
 * thing ever done with it was the two-days-in-a-row rule that quietly makes
 * the plan easier. The list showed the last fortnight, which is exactly short
 * enough to hide the thing that matters: a niggle that comes back every few
 * weeks is a different problem from one bad Tuesday, and you cannot see the
 * difference inside fourteen days.
 *
 * So: ninety days, grouped by spot, with every reported day as a mark on a
 * timeline. Recurrence is a shape, not a number — three clusters spread over
 * two months reads instantly in a way "9 reports" never does.
 *
 * It names nothing and diagnoses nothing. It says where and when, and leaves
 * what that means to a physio.
 */

import { usePains, type Pain } from '../../lib/r13'
import { parseDate, todayISO } from '../../lib/format'

const DAYS = 90

const SIDE: Record<string, string> = {
  left: 'left', right: 'right', both: 'both sides', center: '',
}

const title = (location: string, side: string) => {
  const spot = location.replace(/_/g, ' ')
  const which = SIDE[side] ?? side
  return which ? `${which} ${spot}` : spot
}

type Group = { key: string; label: string; days: Pain[]; worst: number; last: string }

function group(pains: Pain[]): Group[] {
  const by = new Map<string, Group>()
  for (const p of pains) {
    const key = `${p.location}:${p.side}`
    const found = by.get(key)
    if (found) {
      found.days.push(p)
      found.worst = Math.max(found.worst, p.severity)
      if (p.date > found.last) found.last = p.date
    } else {
      by.set(key, {
        key, label: title(p.location, p.side), days: [p],
        worst: p.severity, last: p.date,
      })
    }
  }
  return [...by.values()].sort((a, b) => b.days.length - a.days.length)
}

/** How many separate spells, counting a break of a week or more as a new one. */
function spells(days: Pain[]): number {
  const sorted = [...days].map((p) => p.date).sort()
  let count = 0
  let previous: string | null = null
  for (const date of sorted) {
    if (!previous || (parseDate(date).getTime() - parseDate(previous).getTime()) > 7 * 864e5) {
      count += 1
    }
    previous = date
  }
  return count
}

export function NiggleHistory() {
  const query = usePains(DAYS)
  const pains = query.data ?? []

  if (query.isPending) return null
  if (!pains.length) {
    return (
      <section className="card stack">
        <strong>Niggles</strong>
        <p className="muted small">
          Nothing reported in {DAYS} days. When you answer &ldquo;anything
          hurting?&rdquo; after a run, it builds up here so a knee that keeps
          coming back is visible as a pattern rather than a bad day.
        </p>
      </section>
    )
  }

  const groups = group(pains)
  const today = parseDate(todayISO()).getTime()

  return (
    <section className="card stack niggles">
      <div className="row">
        <strong>Niggles</strong>
        <span className="muted small">last {DAYS} days</span>
      </div>

      <ul className="niggle-list">
        {groups.map((g) => {
          const runs = spells(g.days)
          const lastAgo = Math.round((today - parseDate(g.last).getTime()) / 864e5)
          return (
            <li key={g.key}>
              <div className="niggle-head">
                <span className="niggle-name">{g.label}</span>
                <span className={`niggle-sev is-${g.worst}`}>
                  {g.worst === 1 ? 'niggle' : g.worst === 2 ? 'sore' : 'bad'}
                </span>
              </div>

              <div className="niggle-track" aria-hidden="true">
                {g.days.map((p) => {
                  const ago = (today - parseDate(p.date).getTime()) / 864e5
                  const left = Math.max(0, Math.min(100, ((DAYS - ago) / DAYS) * 100))
                  return (
                    <i key={p.id} data-sev={p.severity} style={{ left: `${left}%` }}
                      title={`${p.date} — severity ${p.severity}`} />
                  )
                })}
              </div>

              <p className="niggle-sub muted small">
                {g.days.length} {g.days.length === 1 ? 'day' : 'days'}
                {runs > 1 && <> across <b>{runs} separate spells</b></>}
                {' · last '}
                {lastAgo === 0 ? 'today' : lastAgo === 1 ? 'yesterday' : `${lastAgo} days ago`}
              </p>
            </li>
          )
        })}
      </ul>

      <p className="muted small">
        Left is {DAYS} days ago, right is today. Something that keeps returning
        after rest is worth a physio rather than another easy week — this screen
        is here to make that visible, not to say what it is.
      </p>
    </section>
  )
}
