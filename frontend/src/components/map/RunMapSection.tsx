import { lazy, Suspense } from 'react'
import { useAuth } from '../../lib/AuthContext'
import { useActivityRoute } from '../../lib/queries'
import { Skeleton } from '../States'

// Leaflet + its CSS live in this chunk only; the main bundle never grows.
const RouteMap = lazy(() => import('./RouteMap'))

/** Run detail → Map: fetches the simplified route, then lazy-loads the map. */
export function RunMapSection({ activityId }: { activityId: number }) {
  const route = useActivityRoute(activityId)
  const { athlete } = useAuth()
  const zones = athlete?.zones?.zones
  const cuts = zones && zones.length >= 5 ? zones.slice(1, 5).map((z) => z.low) : null
  const r = route.data

  if (route.isPending) return <section className="detail-section"><h3>Map</h3><Skeleton height={260} /></section>
  // No GPS (treadmill, indoor), not synced yet, or the endpoint is missing: say so quietly.
  if (!r) return null
  if (!r.available || !r.points?.length || r.points.length < 2) {
    return (
      <section className="detail-section">
        <h3>Map</h3>
        <div className="map-empty">{'No GPS route for this run — indoor, or the watch didn’t record location.'}</div>
      </section>
    )
  }
  return (
    <section className="detail-section">
      <h3>Map</h3>
      <Suspense fallback={<Skeleton height={260} />}>
        <RouteMap route={r} zones={cuts} />
      </Suspense>
    </section>
  )
}
