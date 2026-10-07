import { todayISO } from '../../lib/format'
import { useWeatherToday } from '../../lib/queries'
import { aqiTone, deg, levelTone, ml, windowText } from './weatherUtil'

/** Workout sheet: today's forecast, advisories and hydration (today's workouts only). */
export function WeatherBlock({ date, durationS }: { date: string; durationS: number }) {
  const weather = useWeatherToday()
  const w = weather.data
  if (date !== todayISO() || !w || !w.now) return null
  const aqi = aqiTone(w.now.aqi)
  const h = w.hydration
  const longRun = durationS >= 45 * 60
  return (
    <section className="detail-section weather-block">
      <h3>Weather &amp; hydration</h3>
      <div className="stat-row">
        <div className="stat"><span className="stat-label">Now</span><span className="stat-value">{deg(w.now.temp)}</span></div>
        <div className="stat"><span className="stat-label">Feels like</span><span className="stat-value">{deg(w.now.feels_like)}</span></div>
        {w.now.dew_point != null && <div className="stat"><span className="stat-label">Dew point</span><span className="stat-value">{deg(w.now.dew_point)}</span></div>}
        {w.now.aqi != null && <div className="stat"><span className="stat-label">AQI</span><span className={`stat-value aqi aqi-${aqi.tone}`}>{Math.round(w.now.aqi)}</span></div>}
      </div>
      {w.best_window && <p className="small"><b>Best time to run:</b> {windowText(w.best_window)}{w.best_window.reason ? ` — ${w.best_window.reason}` : ''}</p>}
      {w.advisories.length > 0 && (
        <ul className="advisories">
          {w.advisories.map((a, i) => <li key={i} className={`advisory is-${levelTone(a.level)}`}>{a.text}</li>)}
        </ul>
      )}
      {h && (
        <dl className="fuel">
          {ml(h.before_ml) && <div className="fuel-row"><dt>Before</dt><dd>{ml(h.before_ml)} in the 2 hours before</dd></div>}
          {longRun && ml(h.during_ml_per_h) && <div className="fuel-row"><dt>During</dt><dd>{ml(h.during_ml_per_h)} per hour{h.electrolytes ? ', with electrolytes' : ''}</dd></div>}
          {!longRun && h.electrolytes && <div className="fuel-row"><dt>During</dt><dd>Short run — water if you want it; add electrolytes after.</dd></div>}
          {h.after_note && <div className="fuel-row"><dt>After</dt><dd>{h.after_note}</dd></div>}
        </dl>
      )}
      <p className="muted small">{w.location_name ? `Forecast for ${w.location_name}.` : ''} Change location in Settings.</p>
    </section>
  )
}
