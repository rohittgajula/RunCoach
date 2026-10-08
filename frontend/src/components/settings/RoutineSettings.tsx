import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../lib/AuthContext'
import { api, type Athlete } from '../../lib/auth'
import { errorText } from '../../lib/queries'
import { Toggle } from './HabitSettings'

/** GET /profile/effective/ item — the value every calculation uses, and where it came from. */
type Effective = {
  key: string
  label: string
  value: unknown
  display: string
  source: 'memory' | 'setting' | 'garmin' | 'default'
  fact_id: number | null
  fact_text: string | null
  setting_value: unknown
  garmin_value: unknown
}

const hrs = (min: number) => `${Number((min / 60).toFixed(2)).toString()} h`

/** "7 h · from your memory note" (+ link to the fact) / "set by you" / "Garmin's estimate". */
function Source({ e, overrode }: { e: Effective | undefined; overrode: boolean }) {
  if (!e) return null
  let text: ReactNode
  if (e.source === 'memory') {
    text = <>{e.display} · from your <Link to={e.fact_id ? `/me/memory#fact-${e.fact_id}` : '/me/memory'}>memory note</Link></>
  } else if (e.source === 'setting') {
    text = <>{e.display} · set here{overrode ? ' — now overrides your memory note' : ''}</>
  } else if (e.source === 'garmin') {
    text = <>{e.display} · Garmin’s estimate</>
  } else {
    text = e.value == null || e.display === '' ? 'Not set' : <>{e.display} · default</>
  }
  return <span className="muted small block rt-src">{text}</span>
}

/**
 * R18 §B: sleep need, usual run time and loop distance. Memory notes are the live source;
 * changing a value here is newer, so it takes over (until the fact is edited again).
 */
export function RoutineSettings() {
  const { athlete, updateAthlete } = useAuth()
  const client = useQueryClient()
  const eff = useQuery({ queryKey: ['profile-effective'], queryFn: () => api<{ parameters?: Effective[] | null }>('/profile/effective/') })
  const by = (k: string) => eff.data?.parameters?.find((p) => p.key === k)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  // Keys changed here while a memory note was the source → "now overrides your memory note".
  const [overrode, setOverrode] = useState<Record<string, boolean>>({})
  const save = async (patch: Partial<Athlete>) => {
    const key = Object.keys(patch)[0]
    const wasMemory = by(key)?.source === 'memory'
    setBusy(true)
    setErr('')
    try {
      await updateAthlete(patch)
      if (wasMemory) setOverrode((o) => ({ ...o, [key]: true }))
      await client.invalidateQueries({ queryKey: ['profile-effective'] })
    } catch (e) {
      setErr(errorText(e, 'Could not save that.'))
    } finally {
      setBusy(false)
    }
  }

  const sleep = by('sleep_need_minutes')
  const garmin = athlete?.sleep_need?.garmin_minutes ?? (typeof sleep?.garmin_value === 'number' ? sleep.garmin_value : null)
  const effMin = typeof sleep?.value === 'number' ? sleep.value : athlete?.sleep_need?.minutes ?? garmin ?? 480
  const own = athlete?.sleep_need_minutes ?? null
  const useGarmin = sleep ? sleep.source === 'garmin' || sleep.source === 'default' : own == null
  const step = (d: number) => save({ sleep_need_minutes: Math.min(720, Math.max(240, effMin + d)) })

  const runEff = by('usual_run_time')
  const loopEff = by('loop_distance_km')
  const [time, setTime] = useState<string | null>(null)
  const [loop, setLoop] = useState<string | null>(null)
  const timeShown = time ?? (typeof runEff?.value === 'string' ? runEff.value : athlete?.usual_run_time ?? '')?.slice(0, 5) ?? ''
  const loopShown = loop ?? (typeof loopEff?.value === 'number' ? String(loopEff.value) : athlete?.loop_distance_km != null ? String(athlete.loop_distance_km) : '')
  const saveTime = () => {
    if (time == null) return
    const before = (typeof runEff?.value === 'string' ? runEff.value : athlete?.usual_run_time ?? '')?.slice(0, 5) ?? ''
    if (time !== before) void save({ usual_run_time: time || null })
    setTime(null)
  }
  const saveLoop = () => {
    if (loop == null) return
    const v = loop.trim() === '' ? null : Number(loop.replace(',', '.'))
    if (v != null && (!Number.isFinite(v) || v < 0.1 || v > 50)) return setErr('Loop distance: 0.1–50 km.')
    const before = typeof loopEff?.value === 'number' ? loopEff.value : athlete?.loop_distance_km ?? null
    if (v !== before) void save({ loop_distance_km: v })
    setLoop(null)
  }

  return (
    <div className="stack">
      <Toggle
        label={`Use Garmin’s sleep need${garmin ? ` (${hrs(garmin)})` : ''}`}
        hint="Turn off to set your own. Sleep debt, bedtime and the wake planner use it."
        on={useGarmin}
        onChange={(v) => save({ sleep_need_minutes: v ? null : Math.round(effMin / 15) * 15 })}
      />
      <div className={`stepper-row ${useGarmin ? 'is-muted' : ''}`}>
        <span className="grow">
          <strong>Sleep need</strong>
          <Source e={sleep} overrode={!!overrode.sleep_need_minutes} />
        </span>
        <div className="stepper" role="group" aria-label="Sleep need">
          <button type="button" className="chip" aria-label="Less sleep" disabled={busy || effMin <= 240} onClick={() => step(-15)}>−</button>
          <span className="stepper-value rt-hours" aria-live="polite">{hrs(effMin)}</span>
          <button type="button" className="chip" aria-label="More sleep" disabled={busy || effMin >= 720} onClick={() => step(15)}>+</button>
        </div>
      </div>
      <div className="rt-row">
        <span className="grow">
          <strong>Usual run time</strong>
          {runEff ? <Source e={runEff} overrode={!!overrode.usual_run_time} /> : <span className="muted small block">Auto-sync watches for your run from 15 min before.</span>}
        </span>
        <input type="time" aria-label="Usual run time" value={timeShown} onChange={(e) => setTime(e.target.value)} onBlur={saveTime} />
      </div>
      <div className="rt-row">
        <span className="grow">
          <strong>Loop distance</strong>
          {loopEff ? <Source e={loopEff} overrode={!!overrode.loop_distance_km} /> : <span className="muted small block">Your usual loop — workouts show “≈ N loops”.</span>}
        </span>
        <span className="rt-unit">
          <input inputMode="decimal" placeholder="—" value={loopShown} onChange={(e) => setLoop(e.target.value)} onBlur={saveLoop} aria-label="Loop distance in km" />
          km
        </span>
      </div>
      {err && <p className="field-error">{err}</p>}
    </div>
  )
}
