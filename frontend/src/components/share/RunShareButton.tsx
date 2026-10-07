import { lazy, Suspense, useState } from 'react'
import type { ActivityCard } from '../../lib/types'
import { ShareIcon } from '../Icons'

// R15: the share studio (canvas renderer, GPX/CSV export) loads only when tapped.
const ShareStudio = lazy(() => import('./studio/ShareStudio'))

/** Share chip for a run → the share studio (route + chosen stats over any background). */
export function RunShareButton({ activity }: { activity: ActivityCard; avgHr?: number | null }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="chip" aria-label="Share this run" title="Share this run" onClick={() => setOpen(true)}>
        <ShareIcon />
      </button>
      {open && (
        <Suspense fallback={null}>
          <ShareStudio activity={activity} open onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
