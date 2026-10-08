import { lazy, Suspense, useState } from 'react'
import { qualityChipText, qualityTone, type ActivityQuality } from '../../lib/r17'

// R17 §2: the explanation sheet (chart, choices) is a lazy chunk.
const loadSheet = () => import('./DataCheckSheet')
const DataCheckSheet = lazy(loadSheet)

const MARK = { ok: '✓', warn: '⚠', muted: '–' } as const

/** "Data check" chip in the run sheet: ✓ Clean / ⚠ Fixed 2 HR spikes / Suggested: exclude? / Excluded by you. */
export function DataCheckChip({ activityId, quality }: { activityId: number; quality: ActivityQuality | null | undefined }) {
  const [open, setOpen] = useState(false)
  const [mounted, setMounted] = useState(false)
  if (!quality) return null
  const tone = qualityTone(quality)
  return (
    <>
      <button
        type="button"
        className={`dq-chip is-${tone}`}
        onPointerDown={() => void loadSheet()}
        onClick={() => { setMounted(true); setOpen(true) }}
        aria-label={`Data check: ${qualityChipText(quality)}. Open details`}
      >
        <span aria-hidden="true">{MARK[tone]}</span>
        <span className="dq-chip-k">Data check</span>
        <span>{qualityChipText(quality)}</span>
      </button>
      {mounted && (
        <Suspense fallback={null}>
          <DataCheckSheet open={open} onClose={() => setOpen(false)} activityId={activityId} quality={quality} />
        </Suspense>
      )}
    </>
  )
}
