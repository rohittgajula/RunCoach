import { useReadinessForecast } from '../../lib/queries'
import { Bullets } from '../Bullets'

/** Tomorrow's readiness: a clearly labelled estimate plus what could raise it. */
export function ForecastCard({ detailed = false }: { detailed?: boolean }) {
  const forecast = useReadinessForecast()
  const f = forecast.data
  if (!f) return null
  const has = f.estimate != null
  const levers = (f.levers ?? []).filter((l) => l.gain > 0)
  return (
    <section className="card" aria-label="Tomorrow's readiness forecast">
      <div className="forecast-card">
        <div className="forecast-num" aria-hidden="true">{has ? f.estimate : '–'}</div>
        <div className="grow">
          <p className="forecast-title">
            {has ? <>Tomorrow's readiness ~{f.estimate}</> : 'Tomorrow’s readiness'}
            {' '}<span className="pill">Estimate</span>
          </p>
          <p className="muted small">{f.sentence}</p>
        </div>
      </div>
      {has && levers.length > 0 && (
        <div className="forecast-levers">
          <Bullets items={levers.map((l) => ({ tone: 'good', text: `${l.label} — could add ~${l.gain}` }))} />
        </div>
      )}
      {detailed && has && f.factors.length > 0 && (
        <div className="forecast-levers">
          <Bullets
            items={f.factors.map((x) => ({
              tone: x.effect > 0 ? 'good' : x.effect < 0 ? 'bad' : 'neutral',
              text: `${x.label}${x.effect ? ` (${x.effect > 0 ? '+' : '−'}${Math.abs(x.effect)})` : ''}${x.detail ? ` — ${x.detail}` : ''}`,
            }))}
          />
        </div>
      )}
      {f.note && <p className="chart-caption" style={{ marginTop: 8 }}>{f.note}</p>}
    </section>
  )
}
