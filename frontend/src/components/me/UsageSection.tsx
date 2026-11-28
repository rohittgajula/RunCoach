/**
 * R26 §3: what you actually use.
 *
 * The app has grown five tabs, thirteen pages and sixteen optional Today cards,
 * and until now there was no way to know which of them get opened. That makes
 * removing anything a guess, and a wrong guess deletes something that was being
 * used — so nothing ever gets removed, and the app keeps getting bigger.
 *
 * The useful half of this screen is the second list. Knowing Today is opened daily
 * changes nothing; knowing a card has not been looked at once in a fortnight is
 * what lets it go. That list is computed here rather than on the server, because
 * the catalogue of what exists is already in the frontend (`todayLayout.ts`, the
 * Health section list, the tab list) and a second copy in Python would drift.
 *
 * `days_seen` is given more weight than total views, and deliberately: a screen
 * opened forty times in one sitting and never again is a screen that was bounced
 * off, while one opened once a day for two weeks is part of how the app is used.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { ErrorState, Skeleton } from '../States'
import { TODAY_CARDS } from '../today/todayLayout'

type Row = {
  key: string; kind: string
  views: number; days_seen: number; last_seen: string
}
type Body = {
  days: number; from: string; to: string
  total_views: number; keys: number
  rows: Row[]; retain_days: number; note: string
}

/** The routes worth asking about. Kept here beside the screen that reads them. */
const ROUTES: Array<{ key: string; label: string }> = [
  { key: '/today', label: 'Today' },
  { key: '/plan', label: 'Plan' },
  { key: '/health', label: 'Health · Overview' },
  { key: '/diet', label: 'Food' },
  { key: '/activities', label: 'Runs' },
  { key: '/calendar', label: 'Calendar' },
  { key: '/weather', label: 'Weather' },
  { key: '/health/day', label: 'Health · Day' },
  { key: '/health/sleep', label: 'Health · Sleep' },
  { key: '/health/hr', label: 'Health · Heart rate' },
  { key: '/health/fitness', label: 'Health · Fitness' },
  { key: '/health/progress', label: 'Health · Progress' },
  { key: '/health/habits', label: 'Health · Habits' },
  { key: '/health/more', label: 'Health · More' },
  { key: '/health/labs', label: 'Health · Blood & urine' },
  { key: '/health/sweat', label: 'Health · Sweat' },
  { key: '/health/mirror', label: 'Health · Planned vs done' },
  { key: '/health/heart', label: 'Health · Heart' },
  { key: '/health/goals', label: 'Health · Goals' },
  { key: '/health/experiments', label: 'Health · Experiments' },
  { key: '/health/reports', label: 'Health · Reports' },
  { key: '/health/compare', label: 'Health · Compare' },
  { key: '/health/guides', label: 'Health · Guides' },
  { key: '/health/body', label: 'Health · Weight' },
  { key: '/chat', label: 'Coach' },
  { key: '/me', label: 'Me' },
  { key: '/me/usage', label: 'Me · What you actually use' },
  { key: '/me/races', label: 'Me · Races' },
  { key: '/me/alarms', label: 'Me · Watch alarms' },
  { key: '/me/reminders', label: 'Me · Reminders' },
  { key: '/me/shoes', label: 'Me · Shoes' },
  { key: '/me/badges', label: 'Me · Badges' },
  { key: '/me/calendar', label: 'Me · Calendar sync' },
  { key: '/me/memory', label: 'Me · What the coach knows' },
  { key: '/me/goal', label: 'Me · Set a goal' },
  { key: '/me/account', label: 'Me · Account' },
]

const WINDOWS = [7, 14, 30]

export function UsageSection() {
  const [days, setDays] = useState(14)
  const q = useQuery<Body>({
    queryKey: ['usage', days],
    queryFn: () => api<Body>(`/usage/summary/?days=${days}`),
  })

  if (q.isLoading) return <Skeleton lines={8} />
  if (q.error) return <ErrorState message={errorText(q.error)} onRetry={() => q.refetch()} />
  const body = q.data
  if (!body) return null

  const seen = new Map(body.rows.map((r) => [r.key, r]))
  // Only screens that are genuinely candidates for removal. Account, Coach and
  // the Me sub-pages are reached on purpose when needed, so "not opened in 14
  // days" says nothing about whether they should exist.
  const candidates = ROUTES.filter((r) => !r.key.startsWith('/me') && r.key !== '/chat')
  const unopened = [
    ...candidates.filter((r) => !seen.has(r.key)).map((r) => ({ ...r, what: 'screen' })),
    ...TODAY_CARDS.filter((c) => !seen.has(c.key))
      .map((c) => ({ key: c.key, label: c.label, what: 'Today card' })),
  ]

  return (
    <div className="stack">
      <section className="card stack">
        <div className="usage-windows" role="group" aria-label="How far back">
          {WINDOWS.map((d) => (
            <button key={d} type="button"
                    className={`chip-btn${days === d ? ' is-active' : ''}`}
                    onClick={() => setDays(d)}>
              {d} days
            </button>
          ))}
        </div>
        <p className="muted small">
          {body.total_views} opens across {body.keys} screens and cards, {body.from} to {body.to}.
        </p>
        {!body.rows.length && (
          <p className="small">
            Nothing recorded yet. Use the app for a few days and this fills in — then it
            is worth reading.
          </p>
        )}
        {!!body.rows.length && (
          <ul className="usage-rows">
            {body.rows.map((r) => (
              <li key={`${r.kind}:${r.key}`} className="usage-row">
                <div className="usage-row-main">
                  <span className="usage-key">{label(r.key)}</span>
                  <span className="muted small">{r.kind}</span>
                </div>
                <div className="usage-row-nums">
                  <span><strong className="num">{r.days_seen}</strong> of {body.days} days</span>
                  <span className="muted small">{r.views} opens · last {r.last_seen}</span>
                </div>
                <div className="usage-bar" role="img"
                     aria-label={`opened on ${r.days_seen} of ${body.days} days`}>
                  <span className="usage-fill"
                        style={{ width: `${Math.round((r.days_seen / body.days) * 100)}%` }} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card stack">
        <h2 className="card-title">Not opened once</h2>
        <p className="muted small">
          In {body.days} days. This is the list worth acting on — anything here can go,
          or move somewhere less prominent.
        </p>
        {!unopened.length ? (
          <p className="small">Everything got opened at least once.</p>
        ) : (
          <ul className="usage-unopened">
            {unopened.map((u) => (
              <li key={`${u.what}:${u.key}`}>
                <span>{u.label}</span>
                <span className="muted small">{u.what}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="lab-standing">{body.note}</p>
    </div>
  )
}

const BY_KEY = new Map<string, string>([
  ...ROUTES.map((r) => [r.key, r.label] as [string, string]),
  ...TODAY_CARDS.map((c) => [c.key, c.label] as [string, string]),
])

function label(key: string): string {
  return BY_KEY.get(key) ?? key
}
