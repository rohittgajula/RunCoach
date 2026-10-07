import { useWeatherToday } from '../../lib/queries'
import type { WeatherHour } from '../../lib/types'
import { SunIcon } from '../Icons'
import { Pill } from '../Kit'
import { aqiTone, clock, deg, levelTone, ml } from '../weather/weatherUtil'

const hourOf = (t: string) => {
  const m = /(?:T|^)(\d{1,2}):/.exec(t)
  return m ? Number(m[1]) : null
}

/** Heat shade for one hour's bar: pale → Fuel orange as it gets hotter. */
const heatMix = (feels: number) => (feels < 24 ? 22 : feels < 28 ? 38 : feels < 32 ? 62 : 100)

/** Today: temperature, AQI, hourly bars (best window in Running blue) and the hydration trio. */
export function WeatherCard() {
  const weather = useWeatherToday()
  const w = weather.data
  if (!w || !w.now) return null
  const aqi = aqiTone(w.now.aqi)
  const nowHour = new Date().getHours()
  const hours: WeatherHour[] = (w.hourly ?? []).filter((h) => {
    const hr = hourOf(h.time)
    return hr != null && hr >= Math.min(nowHour, 20) - 1
  }).slice(0, 12)
  const bestStart = w.best_window ? hourOf(w.best_window.start) : null
  const bestEnd = w.best_window ? hourOf(w.best_window.end) : null
  const inBest = (h: WeatherHour) => {
    const hr = hourOf(h.time)
    return hr != null && bestStart != null && bestEnd != null && hr >= bestStart && hr < Math.max(bestEnd, bestStart + 1)
  }
  const temps = hours.map((h) => h.feels_like ?? h.temp).filter((v): v is number => v != null)
  const lo = Math.min(...temps)
  const hi = Math.max(...temps)
  const height = (v: number | null | undefined) => (v == null || !temps.length ? 20 : 25 + ((v - lo) / (hi - lo || 1)) * 70)
  const h = w.hydration
  const heat = w.heat && w.heat !== 'none' ? w.heat.replace(/_/g, ' ') : null
  const warn = w.advisories.filter((a) => levelTone(a.level) !== 'info').slice(0, 2)

  return (
    <section className="card weather-card" aria-label="Weather today">
      <div className="weather-head">
        <SunIcon size={28} className="weather-icon" />
        <div className="grow">
          <div className="weather-temp">
            {deg(w.now.temp)} <small>feels {deg(w.now.feels_like)}</small>
          </div>
          <div className="lbl">
            {[w.location_name, w.now.aqi != null ? `AQI ${Math.round(w.now.aqi)}${aqi.tone === 'ok' ? '' : ` · ${aqi.word}`}` : null].filter(Boolean).join(' · ')}
          </div>
        </div>
        {heat && <Pill topic="fuel">{heat[0].toUpperCase() + heat.slice(1)}</Pill>}
      </div>

      {hours.length >= 3 && (
        <>
          <div className="hour-bars" role="img" aria-label={`Feels-like temperature by hour, ${deg(lo)} to ${deg(hi)}${w.best_window ? `; best time to run ${clock(w.best_window.start)}–${clock(w.best_window.end)}` : ''}`}>
            {hours.map((hr) => {
              const v = hr.feels_like ?? hr.temp
              return (
                <span
                  key={hr.time}
                  title={`${clock(hr.time)} · ${deg(v)}`}
                  style={{
                    height: `${height(v)}%`,
                    background: inBest(hr) ? 'var(--run)' : `color-mix(in srgb, var(--fuel) ${heatMix(v ?? 20)}%, var(--card))`,
                  }}
                />
              )
            })}
          </div>
          <div className="hour-labels">
            <span>{clock(hours[0].time)}</span>
            {w.best_window && <span className="hour-best">Best {clock(w.best_window.start)}–{clock(w.best_window.end)}</span>}
            <span>{clock(hours[hours.length - 1].time)}</span>
          </div>
        </>
      )}
      {hours.length < 3 && w.best_window && <p className="small"><b>Best time to run:</b> {clock(w.best_window.start)}–{clock(w.best_window.end)}</p>}

      {h && (
        <div className="hydration-trio">
          <div><b>{ml(h.before_ml) || '—'}</b><span>before</span></div>
          <div><b>{h.during_ml_per_h != null && ml(h.during_ml_per_h) ? `${ml(h.during_ml_per_h)}/h` : '—'}</b><span>during</span></div>
          <div><b>{h.electrolytes ? '+ salt' : 'water'}</b><span>after</span></div>
        </div>
      )}
      {warn.map((a, i) => <p key={i} className={`weather-advice is-${levelTone(a.level)}`}>{a.text}</p>)}
      {h?.after_note && !warn.length && <p className="muted small">{h.after_note}</p>}
    </section>
  )
}
