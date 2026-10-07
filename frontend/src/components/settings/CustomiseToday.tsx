import { useState } from 'react'
import { useAuth } from '../../lib/AuthContext'
import { errorText } from '../../lib/queries'
import { ChevronDown } from '../Icons'
import { DEFAULT_LAYOUT, resolveLayout, TODAY_CARDS, type TodayCardKey } from '../today/todayLayout'

/**
 * R14 §1 Customise Today: switch optional cards on/off and move them up/down. Saved on
 * the athlete (`today_layout`) as soon as you change it. The hero card always stays.
 */
export function CustomiseToday() {
  const { athlete, updateAthlete } = useAuth()
  const [layout, setLayout] = useState<TodayCardKey[]>(() => resolveLayout(athlete?.today_layout))
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Enabled ones first (in their order), then the rest in catalogue order.
  const rows = [
    ...layout.map((k) => TODAY_CARDS.find((c) => c.key === k)!).filter(Boolean),
    ...TODAY_CARDS.filter((c) => !layout.includes(c.key)),
  ]

  const save = async (next: TodayCardKey[]) => {
    const before = layout
    setLayout(next)
    setError('')
    setBusy(true)
    try {
      await updateAthlete({ today_layout: next })
    } catch (e) {
      setLayout(before)
      setError(errorText(e, 'Could not save the layout.'))
    } finally {
      setBusy(false)
    }
  }
  const toggle = (k: TodayCardKey) => save(layout.includes(k) ? layout.filter((x) => x !== k) : [...layout, k])
  const move = (k: TodayCardKey, dir: -1 | 1) => {
    const i = layout.indexOf(k)
    const j = i + dir
    if (i < 0 || j < 0 || j >= layout.length) return
    const next = [...layout]
    ;[next[i], next[j]] = [next[j], next[i]]
    save(next)
  }
  const isDefault = JSON.stringify(layout) === JSON.stringify(DEFAULT_LAYOUT)

  return (
    <div className="stack-sm">
      <p className="muted small">The top card (readiness + today’s run) always shows. Cards marked “only when…” appear just when there’s something to do.</p>
      <ul className="layout-list">
        {rows.map((c) => {
          const on = layout.includes(c.key)
          const i = layout.indexOf(c.key)
          return (
            <li key={c.key} className="layout-item">
              <button
                type="button"
                role="switch"
                aria-checked={on}
                aria-label={`Show ${c.label} on Today`}
                className={`switch ${on ? 'is-on' : ''}`}
                disabled={busy}
                onClick={() => toggle(c.key)}
              />
              <span className="grow">
                <b className="block">{c.label}</b>
                <span className="muted small">{c.hint}</span>
              </span>
              {on && (
                <>
                  <button type="button" className="icon-btn" aria-label={`Move ${c.label} up`} disabled={busy || i === 0} onClick={() => move(c.key, -1)}>
                    <ChevronDown size={18} className="layout-up" />
                  </button>
                  <button type="button" className="icon-btn" aria-label={`Move ${c.label} down`} disabled={busy || i === layout.length - 1} onClick={() => move(c.key, 1)}>
                    <ChevronDown size={18} />
                  </button>
                </>
              )}
            </li>
          )
        })}
      </ul>
      {!isDefault && (
        <button type="button" className="link-btn small" disabled={busy} onClick={() => save(DEFAULT_LAYOUT)}>Reset to default</button>
      )}
      {error && <p className="bad small">{error}</p>}
    </div>
  )
}
