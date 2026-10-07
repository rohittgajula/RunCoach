import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { Disclosure, SectionSummary } from '../components/Disclose'
import { DropIcon, SunIcon } from '../components/Icons'
import { CardHead, Pill } from '../components/Kit'
import { PageHeader } from '../components/PageHeader'
import { useShell } from '../components/Shell'
import { Empty, ErrorState, Skeleton } from '../components/States'
import { WeatherSwapChips } from '../components/weather/WeatherSwapChip'
import { aqiTone, clock, deg, levelTone, ml } from '../components/weather/weatherUtil'
import { dur, parseDate, todayISO } from '../lib/format'
import { errorText } from '../lib/queries'
import { useWeatherReport, type DayVerdict, type RunVerdict, type WeatherReport, type WeatherReportHour } from '../lib/r14'

const VERDICT: Record<DayVerdict, { word: string; topic: 'ok' | 'habits' | 'bad' }> = {
  good: { word: 'Good to run', topic: 'ok' },
  caution: { word: 'Take care', topic: 'habits' },
  bad: { word: 'Poor for running', topic: 'bad' },
}
const RUN_COLOR: Record<RunVerdict, string> = {
  good: 'var(--ok)', ok: 'color-mix(in srgb, var(--ok) 45%, var(--fuel))', poor: 'var(--fuel)', bad: 'var(--bad)',
}
const dayName = (iso: string) => {
  if (iso === todayISO()) return 'Today'
  return parseDate(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })
}
const heatMix = (feels: number) => (feels < 24 ? 22 : feels < 28 ? 38 : feels < 32 ? 62 : 100)
const AQI_WORD: Record<string, string> = {
  good: 'Good', moderate: 'Moderate', sensitive: 'Unhealthy for sensitive groups', unhealthy: 'Unhealthy', very_unhealthy: 'Very unhealthy', hazardous: 'Hazardous',
}

/**
 * R14 §3 Weather (tap the weather tile on Today): now, the next 48 h in lanes with the
 * best run windows, 7 days, sunrise/sunset, hydration & food, and this week's runs
 * against the forecast. Summary first; the details are one tap down.
 */
export default function Weather() {
  const q = useWeatherReport()
  const r = q.data
  return (
    <div className="page weather-page">
      <PageHeader title="Weather" back={true} sub={r?.location_name ?? undefined} />
      {q.isPending && <><section className="card"><Skeleton lines={4} /></section><section className="card"><Skeleton height={180} /></section></>}
      {q.isError && !r && <ErrorState message={errorText(q.error, 'The forecast did not load.')} onRetry={() => q.refetch()} />}
      {r === null && <Empty title="Weather report isn’t available yet">Check back after the next update.</Empty>}
      {r && !r.available && <NoWeather reason={r.reason} />}
      {r && r.available && <Report r={r} />}
    </div>
  )
}

function NoWeather({ reason }: { reason: string | null }) {
  const { openSettings } = useShell()
  return (
    <Empty
      title={reason === 'no_location' ? 'Where do you run?' : 'The forecast is unavailable right now'}
      action={reason === 'no_location' ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => openSettings('location')}>Set your location</button> : undefined}
    >
      {reason === 'no_location' ? 'Add your city in Settings → Location (or sync a run with GPS) to get the forecast.' : 'Try again in a little while.'}
    </Empty>
  )
}

function Report({ r }: { r: WeatherReport }) {
  const nextBest = r.best_windows[0]
  const today = r.daily[0]
  return (
    <>
      <NowCard r={r} />
      <WeatherSwapChips />
      <SectionSummary
        title={nextBest ? `Best time to run: ${dayName(nextBest.date)} ${clock(nextBest.start)}–${clock(nextBest.end)}` : 'No clearly good window in the next 48 hours'}
        facts={[
          nextBest?.reason,
          today ? `Today ${deg(today.temp_min)}–${deg(today.temp_max)}${today.precip_prob_max != null ? ` · rain ${today.precip_prob_max}%` : ''}` : null,
          r.pace_slowdown_pct > 0 ? `Heat slows easy pace ~${r.pace_slowdown_pct}% — run by heart rate.` : null,
        ]}
      />
      <HourLanes r={r} />
      <Week r={r} />
      <RunsVsWeather r={r} />
      <Disclosure id="weather-fuel" title="Hydration & food" sub={r.hydration ? `${ml(r.hydration.before_ml)} before · ${r.hydration.during_ml_per_h != null ? `${ml(r.hydration.during_ml_per_h)}/h during` : ''}` : 'For today’s heat'}>
        <FuelAdvice r={r} />
      </Disclosure>
      <p className="muted small centered-text">Forecast: Open-Meteo · updated {new Date(r.generated_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</p>
    </>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string | null }) {
  return (
    <div className="wx-stat">
      <span className="lbl">{label}</span>
      <b>{value}</b>
      {sub && <span className="muted small">{sub}</span>}
    </div>
  )
}

function NowCard({ r }: { r: WeatherReport }) {
  const n = r.now
  if (!n) return null
  const aqi = aqiTone(n.aqi)
  const heat = r.heat && r.heat !== 'cool' ? r.heat.replace(/_/g, ' ') : null
  return (
    <section className="card stack-sm" aria-label="Weather now">
      <div className="weather-head">
        <SunIcon size={32} className="weather-icon" />
        <div className="grow">
          <div className="weather-temp">{deg(n.temp)} <small>feels {deg(n.feels_like)}</small></div>
          <div className="lbl">{n.condition ?? ''}</div>
        </div>
        {heat && <Pill topic="fuel">{heat[0].toUpperCase() + heat.slice(1)}</Pill>}
      </div>
      {n.aqi != null && (
        <p className={`weather-advice is-${aqi.tone === 'ok' ? 'info' : aqi.tone === 'warn' ? 'warn' : 'bad'}`}>
          <b>AQI {Math.round(n.aqi)}{n.aqi_level ? ` · ${AQI_WORD[n.aqi_level] ?? n.aqi_level}` : ''}</b>
          {n.pm25 != null && <span className="muted"> · PM2.5 {Math.round(n.pm25)}</span>}
          {n.aqi_meaning && <span className="block">{n.aqi_meaning}</span>}
        </p>
      )}
      <div className="wx-stats">
        <Stat label="Humidity" value={n.humidity != null ? `${Math.round(n.humidity)}%` : '—'} />
        <Stat label="Dew point" value={deg(n.dew_point)} />
        <Stat label="Wind" value={n.wind != null ? `${Math.round(n.wind)} km/h` : '—'} />
        <Stat label="UV" value={n.uv != null ? String(Math.round(n.uv)) : '—'} sub={n.uv_level ? n.uv_level.replace('_', ' ') : null} />
        <Stat label="Sunrise" value={r.sun?.sunrise ? clock(r.sun.sunrise) : '—'} />
        <Stat label="Sunset" value={r.sun?.sunset ? clock(r.sun.sunset) : '—'} />
      </div>
      {r.advisories.filter((a) => levelTone(a.level) !== 'info').map((a, i) => (
        <p key={i} className={`weather-advice is-${levelTone(a.level)}`}>{a.text}</p>
      ))}
    </section>
  )
}

/** 48 columns, three lanes (feels-like, rain, AQI); best windows outlined in Running blue. */
function HourLanes({ r }: { r: WeatherReport }) {
  const scroller = useRef<HTMLDivElement>(null)
  const hours = r.hourly
  if (hours.length < 3) return null
  const feels = hours.map((h) => h.feels_like ?? h.temp).filter((v): v is number => v != null)
  const lo = Math.min(...feels)
  const hi = Math.max(...feels)
  const bar = (v: number | null) => (v == null ? 0 : 20 + ((v - lo) / (hi - lo || 1)) * 80)
  const hasAqi = hours.some((h) => h.aqi != null)
  const label = (h: WeatherReportHour, i: number) => {
    const hr = Number(/T(\d{2})/.exec(h.time)?.[1] ?? -1)
    if (i === 0) return 'Now'
    if (hr === 0) return parseDate(h.time.slice(0, 10)).toLocaleDateString('en-GB', { weekday: 'short' })
    return hr % 3 === 0 ? clock(h.time) : ''
  }
  return (
    <section className="card stack-sm">
      <CardHead title="Next 48 hours" sub="Feels-like, rain and air · best run windows outlined" />
      <div className="wx-lanes-wrap" ref={scroller} tabIndex={0} aria-label="Hourly forecast, scroll sideways">
        <div className="wx-lanes" style={{ gridTemplateColumns: `64px repeat(${hours.length}, 30px)` }}>
          <span className="wx-lane-name">Feels</span>
          {hours.map((h) => {
            const v = h.feels_like ?? h.temp
            return (
              <span key={`f${h.time}`} className={`wx-cell wx-bar ${h.best ? 'is-best' : ''}`} title={`${clock(h.time)} · feels ${deg(v)}`}>
                <i style={{ height: `${bar(v)}%`, background: `color-mix(in srgb, var(--fuel) ${heatMix(v ?? 20)}%, var(--card-2))` }} />
                <small>{v != null ? Math.round(v) : ''}</small>
              </span>
            )
          })}
          <span className="wx-lane-name">Rain %</span>
          {hours.map((h) => (
            <span key={`r${h.time}`} className={`wx-cell ${h.best ? 'is-best' : ''}`} title={`${clock(h.time)} · rain ${h.precip_prob ?? '—'}%`}>
              <i className="wx-dot" style={{ opacity: h.precip_prob == null ? 0 : 0.15 + (h.precip_prob / 100) * 0.85, background: 'var(--sleep)' }} />
              <small>{h.precip_prob != null && h.precip_prob >= 20 ? h.precip_prob : ''}</small>
            </span>
          ))}
          {hasAqi && <span className="wx-lane-name">AQI</span>}
          {hasAqi && hours.map((h) => (
            <span key={`a${h.time}`} className={`wx-cell ${h.best ? 'is-best' : ''}`} title={`${clock(h.time)} · AQI ${h.aqi ?? '—'}`}>
              <i className="wx-dot" style={{ background: h.aqi == null ? 'transparent' : h.aqi <= 50 ? 'var(--ok)' : h.aqi <= 100 ? 'var(--warn)' : 'var(--bad)' }} />
              <small>{h.aqi != null && h.aqi > 100 ? Math.round(h.aqi) : ''}</small>
            </span>
          ))}
          <span className="wx-lane-name">Run</span>
          {hours.map((h) => (
            <span key={`v${h.time}`} className={`wx-cell ${h.best ? 'is-best' : ''}`}>
              <i className="wx-run" style={{ background: h.run ? RUN_COLOR[h.run] : 'transparent' }} title={h.run ?? ''} />
            </span>
          ))}
          <span />
          {hours.map((h, i) => <span key={`t${h.time}`} className="wx-time">{label(h, i)}</span>)}
        </div>
      </div>
      <div className="chart-key">
        <span><i className="key-band" style={{ background: 'var(--ok)' }} />Good</span>
        <span><i className="key-band" style={{ background: 'var(--fuel)' }} />Poor</span>
        <span><i className="key-band" style={{ background: 'var(--bad)' }} />Bad (≥34° feels, storms, AQI &gt;150)</span>
        <span><i className="key-band" style={{ border: '2px solid var(--run)', background: 'transparent' }} />Best window</span>
      </div>
      {r.best_windows.length > 0 && (
        <ul className="wx-best">
          {r.best_windows.map((b) => (
            <li key={b.date + b.start}>
              <b>{dayName(b.date)} {clock(b.start)}–{clock(b.end)}</b>
              <span className="muted small"> · {b.reason}{b.feels_like != null ? ` · feels ${deg(b.feels_like)}` : ''}{b.aqi != null ? ` · AQI ${Math.round(b.aqi)}` : ''}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Week({ r }: { r: WeatherReport }) {
  if (!r.daily.length) return null
  return (
    <section className="card">
      <CardHead title="7 days" />
      <ul className="wx-days">
        {r.daily.map((d) => (
          <li key={d.date}>
            <span className="wx-day-name">{dayName(d.date)}</span>
            <span className="grow wx-day-mid">
              <span className="block small">{d.condition ?? ''}{d.reasons[0] ? <span className="muted"> · {d.reasons[0]}</span> : null}</span>
              <span className="muted small">
                {d.precip_prob_max != null ? <><DropIcon size={12} /> {d.precip_prob_max}%</> : null}
                {d.aqi_max != null ? ` · AQI ${Math.round(d.aqi_max)}` : ''}
              </span>
            </span>
            <span className="wx-day-temp"><b>{deg(d.temp_max)}</b> <span className="muted">{deg(d.temp_min)}</span></span>
            {d.run_verdict && <span className={`wx-verdict is-${d.run_verdict}`} title={VERDICT[d.run_verdict].word} aria-label={VERDICT[d.run_verdict].word} />}
          </li>
        ))}
      </ul>
      <p className="chart-caption" style={{ marginTop: 8 }}>Dot = how runnable the morning and evening windows are. Air quality is forecast 5 days ahead.</p>
    </section>
  )
}

function RunsVsWeather({ r }: { r: WeatherReport }) {
  if (!r.runs.length) return null
  return (
    <section className="card">
      <CardHead title="Your runs vs the weather" sub="This week’s planned runs" />
      <ul className="wx-days">
        {r.runs.map((x) => (
          <li key={x.workout_id}>
            <span className="wx-day-name">{dayName(x.date)}</span>
            <span className="grow wx-day-mid">
              <span className="block small"><b>{x.title}</b> · {dur(x.duration_s)}</span>
              <span className="muted small">
                {x.best_window ? `Best ${clock(x.best_window.start)}–${clock(x.best_window.end)}` : x.reasons[0] ?? ''}
                {x.suggestion_id ? ' · move suggested above' : ''}
              </span>
            </span>
            {x.verdict && <Pill topic={VERDICT[x.verdict].topic}>{VERDICT[x.verdict].word}</Pill>}
          </li>
        ))}
      </ul>
      <Link to="/plan" className="see-details">Open the plan</Link>
    </section>
  )
}

function FuelAdvice({ r }: { r: WeatherReport }) {
  const h = r.hydration
  return (
    <section className="card stack-sm">
      {h && (
        <div className="hydration-trio">
          <div><b>{ml(h.before_ml) || '—'}</b><span>before</span></div>
          <div><b>{h.during_ml_per_h != null && ml(h.during_ml_per_h) ? `${ml(h.during_ml_per_h)}/h` : '—'}</b><span>during</span></div>
          <div><b>{h.electrolytes ? '+ salt' : 'water'}</b><span>after</span></div>
        </div>
      )}
      {h?.after_note && <p className="small">{h.after_note}</p>}
      {r.daily_water_bonus_ml > 0 && <p className="small">Drink about <b>{ml(r.daily_water_bonus_ml)}</b> more water than usual today.</p>}
      {r.food.length > 0 && <ul className="bullets">{r.food.map((f, i) => <li key={i}>{f}</li>)}</ul>}
      {r.advisories.filter((a) => levelTone(a.level) === 'info').map((a, i) => <p key={i} className="muted small">{a.text}</p>)}
    </section>
  )
}
