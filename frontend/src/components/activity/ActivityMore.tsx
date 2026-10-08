import { lazy, Suspense, useState } from 'react'
import { ChipButton } from '../ChipButton'
import { MoreHIcon } from '../Icons'

const loadMenu = () => import('./ActivityMenu')
const ActivityMenu = lazy(loadMenu)

/** R17: run / activity sheet ⋯ → "Delete activity" (menu + confirm are a lazy chunk). */
export function ActivityMore(props: { activityId: number; sport: string; onDeleted: () => void }) {
  const [open, setOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  return (
    <>
      <ChipButton label="More actions" onPointerDown={() => void loadMenu()} onClick={() => { setMounted(true); setOpen(true) }}><MoreHIcon /></ChipButton>
      {mounted && <Suspense fallback={null}><ActivityMenu {...props} open={open} onClose={() => setOpen(false)} /></Suspense>}
    </>
  )
}
