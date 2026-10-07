import { useState } from 'react'
import { ApiError } from '../../lib/auth'
import { errorText, useProgress } from '../../lib/queries'
import type { ProgressWindow } from '../../lib/types'
import { ChevronRight } from '../Icons'
import { InsightCard } from '../insights/Tile'
import { RangeSwitch } from '../RangeSwitch'
import { ErrorState, Skeleton } from '../States'
import { MetricTable } from './MetricTable'
import { ProgressSheet } from './ProgressSheet'
import { WINDOWS, bestsList, windowText } from './progressUtil'

/** Insights → Progress: recent runs vs the ones before; tap through for everything. */
export function ProgressCard() {
  const [window, setWindow] = useState<ProgressWindow>(5)
  const [open, setOpen] = useState(false)
  const progress = useProgress(window)
  if (progress.isError && progress.error instanceof ApiError && progress.error.status === 404) return null
  const data = progress.data
  const newBests = bestsList(data?.bests).filter((b) => b.is_new)

  return (
    <InsightCard title="Progress" className="progress-card">
      <RangeSwitch value={String(window) as `${ProgressWindow}`} onChange={(v) => setWindow(Number(v) as ProgressWindow)} options={WINDOWS} />
      <p className="muted small">{windowText(window)}</p>
      {progress.isPending && <Skeleton lines={5} />}
      {progress.isError && !data && <ErrorState message={errorText(progress.error)} onRetry={() => progress.refetch()} />}
      {data && (
        <div className={progress.isPlaceholderData ? 'is-stale' : ''}>
          <MetricTable metrics={data.metrics ?? []} limit={6} />
          {newBests.length > 0 && (
            <p className="progress-new">🏅 New best: {newBests.map((b) => b.label.toLowerCase()).join(', ')}</p>
          )}
          <button type="button" className="btn btn-secondary btn-block progress-open" onClick={() => setOpen(true)}>
            Chart, bests &amp; review <ChevronRight size={18} />
          </button>
        </div>
      )}
      <ProgressSheet open={open} window={window} onWindow={setWindow} onClose={() => setOpen(false)} />
    </InsightCard>
  )
}
