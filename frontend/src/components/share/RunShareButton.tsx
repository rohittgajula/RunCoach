import { useActivityRoute } from '../../lib/queries'
import type { ActivityCard } from '../../lib/types'
import { ShareButton } from './ShareButton'

/** Share chip for a run: distance, time, pace, avg HR + a route shape with no endpoints. */
export function RunShareButton({ activity, avgHr }: { activity: ActivityCard; avgHr?: number | null }) {
  const route = useActivityRoute(activity.id)
  const r = route.data
  return (
    <ShareButton
      label="Share this run"
      card={() => ({
        kind: 'run',
        title: activity.name || activity.sport || 'Run',
        date: new Date(activity.start).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }),
        distance_m: activity.distance_m ?? null,
        duration_s: activity.duration_s ?? null,
        pace_s_per_km: activity.distance_m > 0 ? activity.duration_s / (activity.distance_m / 1000) : null,
        avg_hr: avgHr ?? null,
        route: r?.available ? r.points.map((p) => [p.lat, p.lon] as [number, number]) : null,
        endpointsHidden: !!r?.hidden_endpoints && (r?.trimmed_m ?? 0) >= 200,
      })}
    />
  )
}
