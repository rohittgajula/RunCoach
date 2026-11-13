import { lazy, Suspense, useState } from 'react'
import { dur } from '../../lib/format'
import type { Strength } from '../../lib/r13'
import { CheckIcon, DumbbellIcon, WatchIcon } from '../Icons'

// Exercise figures + timer live with the Guides; load them when a session is opened.
const StrengthSheet = lazy(() => import('./StrengthSheet'))

/** R13 §4: a strength session in Plan / Today / a day sheet. Tap → exercises. */
export function StrengthCard({ session, compact = false }: { session: Strength; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const s = session
  return (
    <>
      <article
        className={`card cal-card strength-card is-tappable ${s.status === 'skipped' ? 'is-skipped' : ''} ${compact ? 'is-compact' : ''}`}
        data-day-type={s.status === 'completed' ? 'done' : 'gym'}
        onClick={() => setOpen(true)}
        role="button"
        tabIndex={0}
        aria-label={`${s.title}, strength, ${dur(s.duration_s)}. Open exercises.`}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setOpen(true)}
      >
        <header className="cal-card-head">
          <span className="strength-icon" aria-hidden="true"><DumbbellIcon size={20} /></span>
          <span className="cal-card-kind">Strength</span>
          {s.status === 'completed' && <span className="tag tag-ok"><CheckIcon size={14} /> Done</span>}
          {s.status === 'skipped' && <span className="tag">Skipped</span>}
          {s.garmin_status === 'synced' && s.status === 'planned' && (
            <span className="tag tag-plain" title="On your watch"><WatchIcon size={14} /> On watch</span>
          )}
        </header>
        <p className="cal-card-title">{s.title}</p>
        <p className="muted small">
          {dur(s.duration_s)} · {s.exercises.length} moves · level {s.level}{s.after_run ? ' · after your easy run' : ''}
        </p>
      </article>
      {open && (
        <Suspense fallback={null}>
          <StrengthSheet session={s} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
