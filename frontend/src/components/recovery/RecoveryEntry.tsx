import { lazy, Suspense, useState } from 'react'
import { useRecoveryToday } from '../../lib/r17'

// R17 §1: the full-screen timer (routine fetch, figures, audio) is its own chunk.
const loadTimer = () => import('./RecoveryTimer')
const RecoveryTimer = lazy(loadTimer)

function Timer({ activityId, onClose }: { activityId: number; onClose: () => void }) {
  return <Suspense fallback={null}><RecoveryTimer activityId={activityId} onClose={onClose} /></Suspense>
}

/** "Recovery · 6 min" on Today for 6 h after a run (GET /recovery/today/); hidden once done. */
export function RecoveryCard() {
  const r = useRecoveryToday().data?.routine
  const [openId, setOpenId] = useState<number | null>(null)
  // Keep the timer mounted through its "done" screen even though the card then hides.
  if (openId != null) return <Timer activityId={openId} onClose={() => setOpenId(null)} />
  if (!r || r.done || (r.show_until && Date.parse(r.show_until) < Date.now())) return null
  return (
    <button type="button" className="card recovery-card" onPointerDown={() => void loadTimer()} onClick={() => setOpenId(r.activity_id)}>
      <span className="recovery-card-ic" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="4.5" r="2" /><path d="M12 7v7l-4 6M12 14l4 6M6 10l6-2 6 2" /></svg>
      </span>
      <span className="grow">
        <span className="lbl">{r.title || `Recovery · ${r.minutes} min`}</span>
        <span className="recovery-card-title">Stretch it out after your run</span>
      </span>
      <span className="recovery-card-go">Start</span>
    </button>
  )
}

/** "Recovery routine" button in the run sheet (any run, any time). */
export function RecoveryButton({ activityId }: { activityId: number }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="btn btn-secondary recovery-btn" onPointerDown={() => void loadTimer()} onClick={() => setOpen(true)}>
        Recovery routine · stretch &amp; cool down
      </button>
      {open && <Timer activityId={activityId} onClose={() => setOpen(false)} />}
    </>
  )
}
