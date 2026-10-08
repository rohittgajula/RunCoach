import { lazy, Suspense, useEffect, useState } from 'react'
import { useDataReview } from '../../lib/r17'
import { ChevronRight } from '../Icons'

const loadSheet = () => import('./DataReviewSheet')
const DataReviewSheet = lazy(loadSheet)

export function ReviewLauncher({ open, onClose, tab }: { open: boolean; onClose: () => void; tab?: 'pending' | 'reviewed' }) {
  const [mounted, setMounted] = useState(open)
  useEffect(() => { if (open) setMounted(true) }, [open])
  if (!mounted) return null
  return (
    <Suspense fallback={null}>
      <DataReviewSheet open={open} onClose={onClose} initialTab={tab} />
    </Suspense>
  )
}

/** Small, non-nagging "2 things to review" on Health Overview; nothing when there's nothing. */
export function ReviewBadge() {
  const q = useDataReview()
  const [open, setOpen] = useState(false)
  const n = q.data?.pending ?? 0
  if (!n && !open) return null
  return (
    <>
      <button type="button" className="review-badge" onPointerDown={() => void loadSheet()} onClick={() => setOpen(true)}>
        <span className="review-dot" aria-hidden="true" />
        <span className="grow"><b>{n} {n === 1 ? 'thing' : 'things'} to review</b> <span className="muted small">· data that may be off</span></span>
        <ChevronRight size={18} className="muted" />
      </button>
      <ReviewLauncher open={open} onClose={() => setOpen(false)} />
    </>
  )
}

/** "1 run excluded by you · Review" under Progress / Heart charts (excluded runs are left out server-side). */
export function ExcludedNote() {
  const q = useDataReview(true)
  const [open, setOpen] = useState(false)
  const n = (q.data?.items ?? []).filter((i) => i.kind === 'run' && i.decision === 'exclude').length
  if (!n && !open) return null
  return (
    <>
      <p className="excluded-note">
        {n} {n === 1 ? 'run' : 'runs'} excluded by you
        <button type="button" onPointerDown={() => void loadSheet()} onClick={() => setOpen(true)}>Change</button>
      </p>
      <ReviewLauncher open={open} onClose={() => setOpen(false)} tab="reviewed" />
    </>
  )
}
