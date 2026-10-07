import { dayMonth } from '../lib/format'
import { useBody } from '../lib/queries'
import { CardHead, Delta, MetricTile } from './Kit'
import { Sparkline } from './Sparkline'

/** Diet: latest weigh-in (Garmin scale or manual) and body fat, 6-month trend. */
export function BodyCard() {
  const body = useBody('6m')
  const b = body.data
  const l = b?.latest
  if (!b || !l || (l.weight_kg == null && l.body_fat_pct == null)) return null
  const weights = b.series.map((p) => p.weight_kg).filter((v): v is number => v != null)
  const fats = b.series.map((p) => p.body_fat_pct).filter((v): v is number => v != null)
  return (
    <section className="card">
      <CardHead
        title="Body"
        sub={`Last weigh-in ${dayMonth(l.date)}${l.source === 'garmin' ? ' · Garmin' : ''}${b.trend_kg_per_week != null ? ` · ${b.trend_kg_per_week > 0 ? '+' : ''}${b.trend_kg_per_week.toFixed(2)} kg/week` : ''}`}
      />
      <div className="mt-grid">
        {l.weight_kg != null && (
          <MetricTile className="mt-inset" label="Weight" value={l.weight_kg.toFixed(1)} unit="kg" chip={<Delta value={b.change.weight_kg} better={null} format={(v) => v.toFixed(1)} unit="kg" flatWithin={0.1} />}>
            {weights.length >= 2 && <Sparkline values={weights} height={30} color="var(--fuel)" />}
          </MetricTile>
        )}
        {l.body_fat_pct != null && (
          <MetricTile className="mt-inset" label="Body fat" value={l.body_fat_pct.toFixed(1)} unit="%" chip={<Delta value={b.change.body_fat_pct} better="lower" format={(v) => v.toFixed(1)} flatWithin={0.1} />}>
            {fats.length >= 2 && <Sparkline values={fats} height={30} color="var(--fuel)" />}
          </MetricTile>
        )}
      </div>
    </section>
  )
}
