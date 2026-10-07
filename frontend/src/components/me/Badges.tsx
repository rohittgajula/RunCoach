import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { dayMonth } from '../../lib/format'
import { errorText, useAchievements, useMarkBadgesSeen } from '../../lib/queries'
import type { Badge } from '../../lib/types'
import { ChevronRight, LockIcon, MedalIcon } from '../Icons'
import { CardHead, Pill } from '../Kit'
import { Empty, ErrorState, Skeleton } from '../States'

const GROUP: Record<string, string> = {
  smoke_free: 'Smoke-free', consistency: 'Consistency', distance: 'Distance', records: 'Records',
  run_streak: 'Run streaks', sleep: 'Sleep',
}

function BadgeCell({ b }: { b: Badge }) {
  const p = b.progress
  const pct = p && p.target ? Math.min(100, (p.current / p.target) * 100) : 0
  return (
    <div className={`badge-cell ${b.earned ? '' : 'is-locked'}`} title={b.description}>
      <span className="badge-medal">{b.earned ? <MedalIcon size={26} /> : <LockIcon size={22} />}</span>
      <span className="badge-name">{b.label}</span>
      {b.earned ? (
        <span className="badge-meta">{b.new ? <Pill topic="habits">New</Pill> : b.earned_on ? dayMonth(b.earned_on) : 'Earned'}</span>
      ) : p ? (
        <>
          <span className="badge-progress" role="progressbar" aria-label={`${b.label} progress`} aria-valuenow={p.current} aria-valuemax={p.target}>
            <span style={{ width: `${pct}%` }} />
          </span>
          <span className="badge-meta">{p.current} / {p.target} {b.unit}</span>
        </>
      ) : null}
    </div>
  )
}

/** Me → Badges: earned vs locked (with progress), grouped. Opening it clears "new". */
export function BadgesSection() {
  const ach = useAchievements()
  const seen = useMarkBadgesSeen()
  const a = ach.data
  const { mutate } = seen
  useEffect(() => {
    if (a && a.unseen > 0) mutate()
  }, [a, mutate])

  if (ach.isPending) return <section className="card"><Skeleton lines={5} /></section>
  if (ach.isError) return <ErrorState message={errorText(ach.error)} onRetry={() => ach.refetch()} />
  if (!a || !a.badges.length) return <Empty title="Badges aren’t available yet">Check back after the next update.</Empty>

  const groups = [...new Set(a.badges.map((b) => b.group))]
  const earned = a.badges.filter((b) => b.earned).length
  return (
    <div className="stack">
      <section className="card">
        <CardHead title={`${earned} of ${a.badges.length} earned`} sub="Small wins, counted automatically from your runs, sleep and habits." />
        {a.recent.length > 0 && (
          <ul className="bullets">
            {a.recent.slice(0, 5).map((r) => (
              <li key={`${r.kind}-${r.key}-${r.earned_on}`} className="bullet is-good">
                <span className="bullet-dot" aria-hidden="true" />
                <span>{r.kind === 'pr' ? 'New record: ' : ''}{r.label} · {dayMonth(r.earned_on)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {groups.map((g) => (
        <section key={g} className="stack-sm">
          <h2 className="section-title">{GROUP[g] ?? g.replace(/_/g, ' ')}</h2>
          <div className="badge-grid">
            {a.badges.filter((b) => b.group === g).map((b) => <BadgeCell key={b.key} b={b} />)}
          </div>
        </section>
      ))}
    </div>
  )
}

export function BadgesTeaser() {
  const ach = useAchievements()
  const a = ach.data
  if (!a || !a.badges.length) return null
  const earned = a.badges.filter((b) => b.earned)
  const latest = [...earned].sort((x, y) => (y.earned_on ?? '').localeCompare(x.earned_on ?? ''))[0]
  return (
    <Link to="/me/badges" className="card link-row">
      <span className="link-row-icon" style={{ background: 'var(--habits-tint)', color: 'var(--habits-ink)' }}><MedalIcon /></span>
      <span className="grow">
        <span className="link-row-title">Badges {a.unseen > 0 && <Pill topic="habits">{a.unseen} new</Pill>}</span>
        <span className="link-row-text">{earned.length} of {a.badges.length} earned{latest ? ` · latest: ${latest.label}` : ''}</span>
      </span>
      <ChevronRight size={18} className="muted" />
    </Link>
  )
}

const SHOWN_KEY = 'runcoach.badges.toasted'

function readShown(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SHOWN_KEY) ?? '[]') as string[])
  } catch {
    return new Set()
  }
}

/** App-wide: a toast the first time a new badge shows up; tap opens Me → Badges. */
export function BadgeToast() {
  const ach = useAchievements()
  const navigate = useNavigate()
  const [badge, setBadge] = useState<Badge | null>(null)
  const shown = useRef<Set<string>>(readShown())

  useEffect(() => {
    const next = ach.data?.badges.find((b) => b.earned && b.new && !shown.current.has(b.key))
    if (!next) return
    shown.current.add(next.key)
    try {
      localStorage.setItem(SHOWN_KEY, JSON.stringify([...shown.current].slice(-100)))
    } catch {
      /* storage blocked — the toast may repeat next load */
    }
    setBadge(next)
  }, [ach.data])

  useEffect(() => {
    if (!badge) return
    const t = setTimeout(() => setBadge(null), 6000)
    return () => clearTimeout(t)
  }, [badge])

  if (!badge) return null
  return (
    <button type="button" className="badge-toast" role="status" onClick={() => { setBadge(null); navigate('/me/badges') }}>
      <span className="badge-medal"><MedalIcon size={22} /></span>
      <span>
        <b className="block">New badge: {badge.label}</b>
        <span className="muted small">{badge.description}</span>
      </span>
    </button>
  )
}
