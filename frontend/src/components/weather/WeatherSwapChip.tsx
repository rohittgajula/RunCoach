import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../lib/AuthContext'
import { errorText } from '../../lib/queries'
import { useDecideSuggestion, useWeatherSuggestions, type WeatherSuggestion } from '../../lib/r14'

/**
 * R14 §3 on Today and Plan: "Weather: move Thu run to Fri? [Move] [Keep]". Only while a
 * suggestion is pending; nothing moves until Move (unless auto-apply is on in Settings).
 */
export function WeatherSwapChips() {
  const q = useWeatherSuggestions()
  const list = (q.data?.suggestions ?? []).filter((s) => s.status === 'pending')
  if (!list.length) return null
  return <>{list.slice(0, 2).map((s) => <SwapChip key={s.id} s={s} />)}</>
}

function SwapChip({ s }: { s: WeatherSuggestion }) {
  const decide = useDecideSuggestion()
  const [done, setDone] = useState<'' | 'apply' | 'dismiss'>('')
  const act = (action: 'apply' | 'dismiss') =>
    decide.mutate({ id: s.id, action }, { onSuccess: () => setDone(action) })
  if (done) {
    return (
      <div className="slim-chip" role="status">
        <span aria-hidden="true">🌦️</span>
        <span className="grow">{done === 'apply' ? 'Moved — your plan and watch are updated.' : 'Kept as planned.'}</span>
      </div>
    )
  }
  return (
    <div className="slim-chip weather-swap" aria-label="Weather suggestion">
      <span aria-hidden="true">🌦️</span>
      <Link to="/weather" className="grow" style={{ color: 'inherit', textDecoration: 'none' }}>
        <b className="block">{s.text}</b>
        {s.reason && <span className="muted small block">{s.reason}</span>}
        {decide.isError && <span className="bad small block">{errorText(decide.error, 'That no longer fits the plan.')}</span>}
      </Link>
      <span className="slim-chip-actions">
        <button type="button" className="btn btn-secondary btn-sm" disabled={decide.isPending} onClick={() => act('dismiss')}>Keep</button>
        <button type="button" className="btn btn-primary btn-sm" disabled={decide.isPending} onClick={() => act('apply')}>Move</button>
      </span>
    </div>
  )
}

/** Settings → Weather: "Auto-apply weather swaps" (saved at once). */
export function WeatherSwapSetting() {
  const { athlete, updateAthlete } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const on = !!athlete?.weather_auto_apply
  const toggle = async () => {
    setBusy(true)
    setError('')
    try {
      await updateAthlete({ weather_auto_apply: !on })
    } catch (e) {
      setError(errorText(e, 'Could not save.'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="stack-sm">
      <div className="switch-row">
        <span className="grow">
          <strong>Auto-apply weather swaps</strong>
          <span className="muted small block">
            When a run day looks too hot, stormy or smoky, move the run to a better day this week without asking. Off: you get a Move / Keep suggestion.
          </span>
        </span>
        <button type="button" role="switch" aria-checked={on} aria-label="Auto-apply weather swaps" className={`switch ${on ? 'is-on' : ''}`} disabled={busy} onClick={toggle} />
      </div>
      {error && <p className="bad small">{error}</p>}
      <Link to="/weather" className="small">Open the weather report</Link>
    </div>
  )
}
