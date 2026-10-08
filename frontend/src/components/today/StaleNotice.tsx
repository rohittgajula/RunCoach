import { useToday } from '../../lib/queries'
import { useSyncing } from '../../lib/syncFlag'

/**
 * R16 §C: one line when today's sleep/readiness hasn't arrived yet ("Showing yesterday's
 * sleep — your watch hasn't synced last night yet.") with a Sync button. Fresh → nothing.
 */
export function StaleNotice({ onSync }: { onSync: () => void }) {
  const f = useToday().data?.freshness
  const syncing = useSyncing()
  if (!f?.stale || !f.stale_text) return null
  return (
    <div className="stale-note" role="status">
      <p>{f.stale_text}</p>
      <button type="button" className="btn btn-secondary" onClick={onSync} disabled={syncing}>
        {syncing ? 'Syncing…' : 'Sync'}
      </button>
    </div>
  )
}
