import { useWeatherToday } from '../../lib/queries'
import { aqiTone, deg, windowText } from './weatherUtil'

/** Today card: "31° · feels 36° · AQI 82 · Best 6:00–7:30 am". Hidden without weather. */
export function WeatherChip() {
  const weather = useWeatherToday()
  const w = weather.data
  if (!w || !w.now) return null
  const aqi = aqiTone(w.now.aqi)
  const worst = w.advisories.find((a) => /bad|warn|caution/i.test(a.level))
  return (
    <div className="weather-chip" aria-label="Weather today" title={w.location_name ?? undefined}>
      <span className="weather-temp">{deg(w.now.temp)}</span>
      <span className="weather-meta">
        <span>{w.now.condition || 'Now'}</span>
        <span className="muted">
          feels {deg(w.now.feels_like)}
          {w.now.aqi != null && <> · <b className={`aqi aqi-${aqi.tone}`}>AQI&nbsp;{Math.round(w.now.aqi)}</b></>}
        </span>
      </span>
      {w.best_window && (
        <span className="weather-best" title={w.best_window.reason}>
          <span className="muted small">Best run</span>
          <b>{windowText(w.best_window)}</b>
        </span>
      )}
      {worst && <p className={`weather-advice is-${/bad|warn/i.test(worst.level) ? 'bad' : 'warn'}`}>{worst.text}</p>}
    </div>
  )
}
