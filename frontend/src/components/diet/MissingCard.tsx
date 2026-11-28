/**
 * What has actually been missing, over two weeks.
 *
 * No model touches this. Whether his protein has averaged 61 g against a 116 g
 * target is arithmetic, and a number is harder to argue with than a sentence —
 * which is the point, because the honest answer here is usually unwelcome.
 *
 * It stays silent below four logged days. An "average" over two days is not an
 * average, and telling someone their diet is short on the strength of one
 * skipped lunch is how an app loses the right to say anything at all.
 */

import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/auth'

type Short = { macro: string; label: string; average: number; target: number; gap: number; pct: number }
type Missing = {
  logged_days: number
  enough: boolean
  window_days?: number
  averages: Record<string, number>
  targets: Record<string, number>
  short: Short[]
}

const UNIT: Record<string, string> = { protein_g: 'g', carbs_g: 'g', kcal: 'kcal' }

export function MissingCard() {
  const q = useQuery({
    queryKey: ['diet-missing'],
    queryFn: () => api<Missing>('/diet/missing/'),
    staleTime: 15 * 60_000,
    retry: false,
  })
  const d = q.data
  if (!d) return null

  if (!d.enough) {
    return (
      <section className="card ms">
        <h2 className="card-title">What’s missing</h2>
        <p className="muted small">
          {d.logged_days === 0
            ? 'Log a few days of food and this will tell you what you’re consistently short on.'
            : `${d.logged_days} day${d.logged_days === 1 ? '' : 's'} logged so far. A few more and this
               will show what you’re consistently short on — an average over ${d.logged_days}
               day${d.logged_days === 1 ? '' : 's'} isn’t one.`}
        </p>
      </section>
    )
  }

  if (!d.short.length) {
    return (
      <section className="card ms">
        <h2 className="card-title">What’s missing</h2>
        <p className="small">
          Nothing consistently short across your last {d.logged_days} logged days.
        </p>
      </section>
    )
  }

  return (
    <section className="card stack ms">
      <h2 className="card-title">What’s missing</h2>
      <p className="muted small">
        Your last {d.logged_days} logged days, against what those days asked for.
      </p>
      {d.short.map((s) => (
        <div key={s.macro} className="ms-row">
          <div className="ms-row-head">
            <span className="ms-label">{s.label}</span>
            <span className="ms-nums num">
              {s.average}<span className="ms-of"> / {s.target} {UNIT[s.macro] ?? ''}</span>
            </span>
          </div>
          <div className="ms-bar" role="presentation">
            <span className="ms-fill" style={{ width: `${Math.min(100, s.pct)}%` }} />
          </div>
          <p className="ms-gap">
            Short by {s.gap} {UNIT[s.macro] ?? ''} a day — you’re hitting {s.pct}% of it.
          </p>
        </div>
      ))}
    </section>
  )
}
