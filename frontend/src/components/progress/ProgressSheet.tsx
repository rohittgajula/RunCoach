import { errorText, useProgress } from '../../lib/queries'
import type { ProgressWindow } from '../../lib/types'
import { BottomSheet } from '../BottomSheet'
import { RangeSwitch } from '../RangeSwitch'
import { ErrorState, Skeleton } from '../States'
import { BestsList } from './BestsList'
import { BucketTable } from './BucketTable'
import { ProgressChart } from './ProgressChart'
import { ProgressFocus } from './ProgressFocus'
import { ProgressReviewCard } from './ProgressReviewCard'
import { WINDOWS, bestsList, windowText } from './progressUtil'

/** Everything about the comparison: buckets, chart, bests, focus, AI review. */
export function ProgressSheet({
  open, window, onWindow, onClose,
}: { open: boolean; window: ProgressWindow; onWindow: (w: ProgressWindow) => void; onClose: () => void }) {
  const progress = useProgress(window)
  const data = progress.data
  return (
    <BottomSheet open={open} onClose={onClose} full title="Progress">
      <RangeSwitch value={String(window) as `${ProgressWindow}`} onChange={(v) => onWindow(Number(v) as ProgressWindow)} options={WINDOWS} />
      <p className="muted small centered-text">{windowText(window)}</p>
      {progress.isPending && <Skeleton height={240} />}
      {progress.isError && !data && <ErrorState message={errorText(progress.error)} onRetry={() => progress.refetch()} />}
      {data && (
        <div className={`stack-lg ${progress.isPlaceholderData ? 'is-stale' : ''}`}>
          <section className="card stack">
            <h3 className="habit-sub">Compared</h3>
            <BucketTable data={data} />
          </section>
          <section className="card stack">
            <h3 className="habit-sub">Pace &amp; heart rate</h3>
            <ProgressChart series={data.series ?? []} />
          </section>
          {bestsList(data.bests).length > 0 && (
            <section className="card stack">
              <h3 className="habit-sub">Bests</h3>
              <BestsList bests={bestsList(data.bests)} />
            </section>
          )}
          {data.focus?.length > 0 && (
            <section className="card stack">
              <h3 className="habit-sub">What to work on</h3>
              <ProgressFocus focus={data.focus} />
            </section>
          )}
          <section className="card">
            <ProgressReviewCard key={window} review={data.review} window={window} />
          </section>
        </div>
      )}
    </BottomSheet>
  )
}
