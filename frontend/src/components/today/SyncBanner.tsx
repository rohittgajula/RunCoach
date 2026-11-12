/**
 * The watch stopped talking, said where you will see it.
 *
 * Rohit's Garmin session died on 10 October and the only signal was a boolean on
 * a settings page he had no reason to open. For five weeks Today showed a plan
 * built on October data, the coach answered questions about a stale picture with
 * full confidence, and his 5 km projection was derived from a watch that had
 * stopped reporting. Being wrong quietly is worse than being disconnected.
 *
 * So this is a sentence at the top of Today, not a dot. The dot in the shell
 * stays — it is the right weight for "is it connected right now" — but a dot
 * cannot say *since when*, and it is the duration that tells you whether to
 * trust the screen underneath.
 *
 * Deliberately not dismissible. A banner you can dismiss is one you dismiss
 * once and never think about again, which returns the app to failing silently
 * by a slightly longer route. It disappears when the thing it reports is fixed,
 * and not before.
 */

import { Link } from 'react-router-dom'
import { useToday } from '../../lib/queries'
import { useSyncing } from '../../lib/syncFlag'

export type SyncVerdict = {
  level: 'ok' | 'quiet' | 'stale' | 'broken'
  connected: boolean
  hours_since_sync: number | null
  days_since_activity: number | null
  last_sync_at: string | null
  last_activity_date: string | null
  headline: string
  detail: string
  action: 'reconnect' | 'sync' | ''
}

const TONE: Record<string, string> = {
  broken: 'sync-banner-bad',
  stale: 'sync-banner-warn',
  quiet: 'sync-banner-quiet',
}

export function SyncBanner({ onSync }: { onSync?: () => void }) {
  const sync = useToday().data?.freshness?.sync
  const syncing = useSyncing()
  if (!sync || sync.level === 'ok') return null

  return (
    <section className={`sync-banner ${TONE[sync.level] ?? ''}`} role="status">
      <div className="sync-banner-text">
        <strong>{sync.headline}</strong>
        <p>{sync.detail}</p>
        {sync.days_since_activity != null && sync.days_since_activity > 2 && (
          <p className="sync-banner-since">
            Last recorded activity: {new Date(`${sync.last_activity_date}T00:00:00`)
              .toLocaleDateString(undefined, { day: 'numeric', month: 'long' })}
            {' '}· {sync.days_since_activity} days ago.
          </p>
        )}
      </div>

      {sync.action === 'reconnect' ? (
        <Link to="/me/account" className="btn-primary sync-banner-action">
          Reconnect
        </Link>
      ) : sync.action === 'sync' && onSync ? (
        <button
          type="button"
          className="btn-secondary sync-banner-action"
          onClick={onSync}
          disabled={syncing}
        >
          {syncing ? 'Syncing…' : 'Sync now'}
        </button>
      ) : null}
    </section>
  )
}
