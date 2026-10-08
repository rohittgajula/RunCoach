import { useEffect, useRef, useState } from 'react'
import { mmss, parseDuration } from './editModel'

/**
 * Duration: −1 min · −15 s · [3:00] · +15 s · +1 min. Tap the value to type
 * ("3", "3:30", "90s"); Enter or leaving the field applies it.
 */
export function DurationStepper({
  value, onChange, min, max, label,
}: { value: number; onChange: (s: number) => void; min: number; max: number; label: string }) {
  const [typing, setTyping] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { if (typing != null) input.current?.select() }, [typing != null]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (s: number) => onChange(Math.max(min, Math.min(max, Math.round(s))))
  const commit = () => {
    if (typing == null) return
    const s = parseDuration(typing)
    if (s != null) set(s)
    setTyping(null)
  }
  return (
    <div className="ed-dur" role="group" aria-label={label}>
      <button type="button" className="ed-sbtn" onClick={() => set(value - 60)} disabled={value <= min} aria-label="1 minute less">−1m</button>
      <button type="button" className="ed-sbtn" onClick={() => set(value - 15)} disabled={value <= min} aria-label="15 seconds less">−15s</button>
      {typing != null ? (
        <input
          ref={input}
          className="ed-dur-input"
          inputMode="numeric"
          value={typing}
          aria-label={`${label}, minutes:seconds`}
          onChange={(e) => setTyping(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit() }
            if (e.key === 'Escape') { e.stopPropagation(); setTyping(null) }
          }}
        />
      ) : (
        <button type="button" className="ed-dur-value" onClick={() => setTyping(mmss(value))} aria-label={`${label} ${mmss(value)}, tap to type`}>
          {mmss(value)}
        </button>
      )}
      <button type="button" className="ed-sbtn" onClick={() => set(value + 15)} disabled={value >= max} aria-label="15 seconds more">+15s</button>
      <button type="button" className="ed-sbtn" onClick={() => set(value + 60)} disabled={value >= max} aria-label="1 minute more">+1m</button>
    </div>
  )
}

/** [−] value [+] for bpm, pace and repeat counts. */
export function NumStepper({
  value, onChange, step = 1, min, max, format = String, label, unit,
}: {
  value: number
  onChange: (v: number) => void
  step?: number
  min: number
  max: number
  format?: (v: number) => string
  label: string
  unit?: string
}) {
  const set = (v: number) => onChange(Math.max(min, Math.min(max, v)))
  return (
    <div className="ed-num" role="group" aria-label={label}>
      <button type="button" className="ed-sbtn" onClick={() => set(value - step)} disabled={value <= min} aria-label={`${label} down`}>−</button>
      <span className="ed-num-value" aria-live="polite">
        {format(value)}{unit && <small> {unit}</small>}
      </span>
      <button type="button" className="ed-sbtn" onClick={() => set(value + step)} disabled={value >= max} aria-label={`${label} up`}>+</button>
    </div>
  )
}
