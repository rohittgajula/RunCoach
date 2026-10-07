import { useState } from 'react'

/**
 * R13 §3 "Anything hurting?" — a simple front/back body with tappable areas, plus the
 * same areas as big chips (the drawing is small on a phone; the chips are the 44 px
 * targets). Each pain = area × side × severity 1–3. No diagnosis, ever.
 */

export type PainArea = 'foot' | 'ankle' | 'shin' | 'calf' | 'knee' | 'hamstring' | 'quad' | 'hip' | 'lower_back'
export type PainSide = 'left' | 'right' | 'both'
export type PainSpot = { area: PainArea; side: PainSide; severity: 1 | 2 | 3 }

export const PAIN_AREA_LABEL: Record<PainArea, string> = {
  foot: 'Foot', ankle: 'Ankle', shin: 'Shin', calf: 'Calf', knee: 'Knee',
  hamstring: 'Hamstring', quad: 'Thigh (quad)', hip: 'Hip', lower_back: 'Lower back',
}
export const PAIN_AREAS: PainArea[] = ['foot', 'ankle', 'shin', 'calf', 'knee', 'hamstring', 'quad', 'hip', 'lower_back']
export const SEVERITY_LABEL = { 1: 'Niggle', 2: 'Sore', 3: 'Hurts' } as const
const SEVERITY_SUB = { 1: 'Noticeable, doesn’t change how you move', 2: 'Changes how you move a little', 3: 'Painful — you’d stop or limp' } as const

export const sideText = (s: PainSide) => (s === 'both' ? 'both sides' : s)
export const painText = (p: { area?: string; location?: string; side?: string | null }) => {
  const area = p.location ?? p.area ?? ''
  const label = PAIN_AREA_LABEL[area as PainArea] ?? area
  const side = p.side && p.side !== 'both' && p.side !== 'center' && area !== 'lower_back' ? `${p.side} ` : ''
  return `${side}${label.toLowerCase()}`.replace(/^./, (c) => c.toUpperCase())
}

type Zone = { area: PainArea; side: 'left' | 'right' | 'center'; x: number; y: number; w: number; h: number }

/* Viewer's left on the FRONT view is the athlete's RIGHT. */
function legZones(view: 'front' | 'back'): Zone[] {
  const out: Zone[] = []
  const legs: Array<{ side: 'left' | 'right'; x: number }> = view === 'front'
    ? [{ side: 'right', x: 64 }, { side: 'left', x: 102 }]
    : [{ side: 'left', x: 64 }, { side: 'right', x: 102 }]
  for (const { side, x } of legs) {
    out.push({ area: 'hip', side, x, y: 168, w: 34, h: 34 })
    out.push({ area: view === 'front' ? 'quad' : 'hamstring', side, x, y: 204, w: 34, h: 62 })
    out.push({ area: 'knee', side, x, y: 268, w: 34, h: 28 })
    out.push({ area: view === 'front' ? 'shin' : 'calf', side, x: x + 2, y: 298, w: 30, h: 60 })
    out.push({ area: 'ankle', side, x: x + 4, y: 360, w: 26, h: 20 })
    out.push({ area: 'foot', side, x: view === 'front' ? x + (side === 'right' ? -6 : 4) : x + 2, y: 382, w: view === 'front' ? 36 : 30, h: 22 })
  }
  if (view === 'back') out.push({ area: 'lower_back', side: 'center', x: 70, y: 128, w: 60, h: 36 })
  return out
}

function BodyView({ view, spots, onTap }: { view: 'front' | 'back'; spots: PainSpot[]; onTap: (z: Zone) => void }) {
  const zones = legZones(view)
  const sev = (z: Zone) => {
    const s = spots.find((p) => p.area === z.area && (z.side === 'center' || p.side === z.side || p.side === 'both'))
    return s?.severity ?? 0
  }
  return (
    <figure className="bodymap-view">
      <svg viewBox="30 0 140 412" className="bodymap-svg" role="group" aria-label={`Body, ${view}`}>
        {/* silhouette */}
        <g className="bodymap-sil" aria-hidden="true">
          <circle cx="100" cy="30" r="20" />
          <rect x="92" y="48" width="16" height="12" rx="4" />
          <rect x="64" y="58" width="72" height="112" rx="22" />
          <rect x="42" y="64" width="18" height="104" rx="9" transform="rotate(6 51 64)" />
          <rect x="140" y="64" width="18" height="104" rx="9" transform="rotate(-6 149 64)" />
          <rect x="64" y="160" width="72" height="44" rx="14" />
          <rect x="64" y="200" width="34" height="182" rx="14" />
          <rect x="102" y="200" width="34" height="182" rx="14" />
        </g>
        {zones.map((z) => {
          const s = sev(z)
          const name = `${z.side === 'center' ? '' : `${z.side} `}${PAIN_AREA_LABEL[z.area].toLowerCase()}`
          return (
            <rect
              key={`${z.area}-${z.side}`}
              className={`bodymap-zone ${s ? `is-sev-${s}` : ''}`}
              x={z.x} y={z.y} width={z.w} height={z.h} rx={8}
              role="button"
              tabIndex={0}
              aria-label={`${name}${s ? `, ${SEVERITY_LABEL[s as 1 | 2 | 3].toLowerCase()}` : ''}`}
              aria-pressed={s > 0}
              onClick={() => onTap(z)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onTap(z) } }}
            />
          )
        })}
        <text x="34" y="410" className="bodymap-lr">{view === 'front' ? 'R' : 'L'}</text>
        <text x="160" y="410" className="bodymap-lr" textAnchor="end">{view === 'front' ? 'L' : 'R'}</text>
      </svg>
      <figcaption>{view === 'front' ? 'Front' : 'Back'}</figcaption>
    </figure>
  )
}

/** Controlled editor for a list of pain spots. */
export function BodyMap({ value, onChange }: { value: PainSpot[]; onChange: (next: PainSpot[]) => void }) {
  const [focus, setFocus] = useState<PainArea | null>(value[0]?.area ?? null)

  const upsert = (area: PainArea, side: PainSide) => {
    const existing = value.find((p) => p.area === area)
    if (existing) {
      const merged: PainSide = existing.side === side ? side : 'both'
      onChange(value.map((p) => (p.area === area ? { ...p, side: merged } : p)))
    } else onChange([...value, { area, side, severity: 2 }])
    setFocus(area)
  }
  const tapZone = (z: Zone) => {
    const existing = value.find((p) => p.area === z.area)
    // Tapping the only selected side again clears it.
    if (existing && z.side !== 'center' && existing.side === z.side) {
      onChange(value.filter((p) => p.area !== z.area))
      return
    }
    if (existing && z.side === 'center') {
      onChange(value.filter((p) => p.area !== z.area))
      return
    }
    upsert(z.area, z.side === 'center' ? 'both' : z.side)
  }
  const toggleChip = (area: PainArea) => {
    if (value.some((p) => p.area === area)) {
      onChange(value.filter((p) => p.area !== area))
      if (focus === area) setFocus(null)
    } else {
      onChange([...value, { area, side: area === 'lower_back' ? 'both' : 'left', severity: 2 }])
      setFocus(area)
    }
  }
  const patch = (area: PainArea, next: Partial<PainSpot>) => onChange(value.map((p) => (p.area === area ? { ...p, ...next } : p)))

  return (
    <div className="bodymap">
      <div className="bodymap-views">
        <BodyView view="front" spots={value} onTap={tapZone} />
        <BodyView view="back" spots={value} onTap={tapZone} />
      </div>
      <div className="ci-chips" role="group" aria-label="Where does it hurt?">
        {PAIN_AREAS.map((a) => (
          <button
            key={a}
            type="button"
            aria-pressed={value.some((p) => p.area === a)}
            className={`ci-chip ${value.some((p) => p.area === a) ? 'is-on' : ''}`}
            onClick={() => toggleChip(a)}
          >
            {PAIN_AREA_LABEL[a]}
          </button>
        ))}
      </div>
      {value.map((p) => (
        <div key={p.area} className={`bodymap-spot ${focus === p.area ? 'is-focus' : ''}`}>
          <div className="bodymap-spot-head">
            <b>{PAIN_AREA_LABEL[p.area]}</b>
            <button type="button" className="link-btn" onClick={() => onChange(value.filter((x) => x.area !== p.area))}>Remove</button>
          </div>
          {p.area !== 'lower_back' && (
            <div className="segmented segmented-full segmented-sm" role="radiogroup" aria-label={`${PAIN_AREA_LABEL[p.area]}: side`}>
              {(['left', 'right', 'both'] as const).map((s) => (
                <button key={s} type="button" role="radio" aria-checked={p.side === s} className={`segmented-option ${p.side === s ? 'is-active' : ''}`} onClick={() => patch(p.area, { side: s })}>
                  {s === 'both' ? 'Both' : s === 'left' ? 'Left' : 'Right'}
                </button>
              ))}
            </div>
          )}
          <div className="segmented segmented-full segmented-sm" role="radiogroup" aria-label={`${PAIN_AREA_LABEL[p.area]}: how bad`}>
            {([1, 2, 3] as const).map((s) => (
              <button key={s} type="button" role="radio" aria-checked={p.severity === s} className={`segmented-option ${p.severity === s ? 'is-active' : ''}`} onClick={() => patch(p.area, { severity: s })}>
                {SEVERITY_LABEL[s]}
              </button>
            ))}
          </div>
          <p className="muted small">{SEVERITY_SUB[p.severity]}</p>
        </div>
      ))}
      {value.some((p) => p.severity >= 2) && (
        <p className="bodymap-note small">Keep runs easy or rest while it’s sore. If it’s still there in a few days, or gets worse, see a physio.</p>
      )}
    </div>
  )
}
