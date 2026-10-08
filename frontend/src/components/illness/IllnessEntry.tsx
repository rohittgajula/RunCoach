import { lazy, Suspense, useState } from 'react'
import type { Illness } from '../../lib/r17'
import { ChipButton } from '../ChipButton'
import { MoreHIcon } from '../Icons'
import { Skeleton } from '../States'

// R17 §10: Today's rest hero, its sheets and the ⋯ menu are lazy chunks; only these
// two small wrappers ship in the main bundle.
const LazyHero = lazy(() => import('./IllnessHero'))

/** Calm "Rest & recover" hero instead of readiness + workout while unwell. */
export function IllnessHero({ illness }: { illness: Illness }) {
  return (
    <Suspense fallback={<section className="card today-hero"><Skeleton lines={3} /></section>}>
      <LazyHero illness={illness} />
    </Suspense>
  )
}

const loadMenu = () => import('../today/TodayMoreMenu')
const TodayMoreMenu = lazy(loadMenu)

/** Today ⋯ — "I’m sick or injured" / "I’m better", "Start an experiment" (menu is lazy). */
export function TodayMore() {
  const [open, setOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  return (
    <>
      <ChipButton label="More" className="chip-plain" onPointerDown={() => void loadMenu()} onClick={() => { setMounted(true); setOpen(true) }}>
        <MoreHIcon />
      </ChipButton>
      {mounted && <Suspense fallback={null}><TodayMoreMenu open={open} onClose={() => setOpen(false)} /></Suspense>}
    </>
  )
}
