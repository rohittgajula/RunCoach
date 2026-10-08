import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { pace } from '../../lib/format'
import type { ActivityRoute, RoutePoint } from '../../lib/types'
import { RangeSwitch } from '../RangeSwitch'
import { ElevationProfile } from './ElevationProfile'

/**
 * R11 run map — its own lazy chunk (Leaflet + CSS never touch the main bundle).
 * Route coloured by pace / HR / run-walk, km markers, start/finish, tap → the numbers at
 * that point, and the elevation profile under it shares the selected point.
 */

type Mode = 'pace' | 'hr' | 'runwalk'

export const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'

/** Leaflet writes colours into SVG attributes, where var() does not resolve. */
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Garmin Connect's familiar scale: slow/low = blue → light blue → green → yellow →
 * orange → red = fast/high. Fixed hex: these sit on map tiles, not on our cards, so they
 * stay the same in light and dark (the dark outline carries the contrast).
 */
const SCALE = ['#1f5fd6', '#3fb4f0', '#2cb84f', '#f2cf1d', '#f68a1f', '#e3322b']
/** Five HR zones on the same scale (Z1 blue … Z5 red). */
const ZONE_SCALE = ['#1f5fd6', '#3fb4f0', '#2cb84f', '#f68a1f', '#e3322b']
const OUTLINE = '#0b0d10'

function quantiles(values: number[], bins: number): number[] {
  const v = [...values].sort((a, b) => a - b)
  if (!v.length) return []
  return Array.from({ length: bins - 1 }, (_, i) => v[Math.min(v.length - 1, Math.floor(((i + 1) / bins) * v.length))])
}

type Legend = { kind: 'scale'; colors: string[]; low: string; high: string; lowTitle?: string; highTitle?: string } | { kind: 'items'; items: Array<{ color: string; label: string }> }

function colouring(points: RoutePoint[], mode: Mode, zones: number[] | null, paceRange: { min: number; max: number } | null): { colorOf: (p: RoutePoint) => string | null; legend: Legend } {
  if (mode === 'runwalk') {
    const run = cssVar('--run', '#2f6bff')
    const walk = cssVar('--walk-map', '#8a94a3')
    return {
      colorOf: (p) => (p.segment === 'walk' ? walk : p.segment === 'stop' ? null : run),
      legend: { kind: 'items', items: [{ color: run, label: 'Run' }, { color: walk, label: 'Walk' }] },
    }
  }
  if (mode === 'hr') {
    // Zone bounds when known (Z2 low … Z5 low), else the run's own sixths.
    const byZone = !!zones && zones.length === 4
    const pal = byZone ? ZONE_SCALE : SCALE
    const cuts = byZone ? zones! : quantiles(points.map((p) => p.hr).filter((h): h is number => h != null), SCALE.length)
    const bin = (h: number) => Math.min(pal.length - 1, cuts.filter((c) => h >= c).length)
    return {
      colorOf: (p) => (p.hr == null ? null : pal[bin(p.hr)]),
      legend: { kind: 'scale', colors: pal, low: byZone ? 'Z1' : 'Lower', high: byZone ? 'Z5' : 'Higher' },
    }
  }
  // Pace: more seconds per km = slower = blue; fewer = faster = red.
  const paces = points.map((p) => p.pace_s_per_km).filter((s): s is number => s != null && s > 0 && s < 1800)
  // The server's 5th–95th percentile range keeps a GPS spike from flattening the colours.
  const lo = paceRange?.min ?? (paces.length ? Math.min(...paces) : null)
  const hi = paceRange?.max ?? (paces.length ? Math.max(...paces) : null)
  const n = SCALE.length
  const cuts = lo != null && hi != null && hi > lo ? Array.from({ length: n - 1 }, (_, i) => lo + ((i + 1) / n) * (hi - lo)) : quantiles(paces, n)
  const bin = (s: number) => n - 1 - cuts.filter((c) => s > c).length
  return {
    colorOf: (p) => (p.pace_s_per_km == null || p.pace_s_per_km <= 0 ? null : SCALE[bin(p.pace_s_per_km)]),
    legend: {
      kind: 'scale', colors: SCALE, low: 'Slower', high: 'Faster',
      lowTitle: hi ? `${pace(hi)} /km and slower` : undefined, highTitle: lo ? `${pace(lo)} /km and faster` : undefined,
    },
  }
}

function nearestIndex(points: RoutePoint[], lat: number, lon: number): number {
  let best = 0
  let bestD = Infinity
  const k = Math.cos((lat * Math.PI) / 180)
  points.forEach((p, i) => {
    const d = (p.lat - lat) ** 2 + ((p.lon - lon) * k) ** 2
    if (d < bestD) { bestD = d; best = i }
  })
  return best
}

const kmText = (m: number) => `${(m / 1000).toFixed(2)} km`

export default function RouteMap({ route, zones }: { route: ActivityRoute; zones?: number[] | null }) {
  const host = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const lineLayer = useRef<L.LayerGroup | null>(null)
  const dotRef = useRef<L.CircleMarker | null>(null)
  const points = route.points
  const hasHr = points.some((p) => p.hr != null)
  const hasPace = points.some((p) => p.pace_s_per_km != null)
  const hasKind = route.has_segments || points.some((p) => p.segment === 'walk')
  const [mode, setMode] = useState<Mode>(hasPace ? 'pace' : hasHr ? 'hr' : 'runwalk')
  const [selected, setSelected] = useState<number | null>(null)
  const { colorOf, legend } = useMemo(() => colouring(points, mode, zones ?? null, route.pace_range), [points, mode, zones, route.pace_range])

  // Map + tiles + static markers, once per route.
  useEffect(() => {
    if (!host.current || !points.length) return
    const still = reducedMotion()
    const map = L.map(host.current, {
      zoomControl: true,
      attributionControl: true,
      scrollWheelZoom: false,
      zoomAnimation: !still,
      fadeAnimation: !still,
      markerZoomAnimation: !still,
      inertia: !still,
      tapTolerance: 20,
    })
    map.attributionControl.setPrefix('<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>')
    L.tileLayer(TILE_URL, {
      maxZoom: 19,
      attribution: ATTRIBUTION,
      // The site sends Referrer-Policy: same-origin; OSM's tile policy asks for a referrer.
      referrerPolicy: 'strict-origin-when-cross-origin',
    } as L.TileLayerOptions).addTo(map)
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lon] as [number, number]))
    map.fitBounds(bounds, { padding: [18, 18], animate: false })

    const first = route.start ?? points[0]
    const last = route.finish ?? points[points.length - 1]
    const pin = (cls: string, text: string) =>
      L.divIcon({ className: `map-pin ${cls}`, html: `<span aria-hidden="true">${text}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] })
    L.marker([first.lat, first.lon], { icon: pin('is-start', '▶'), keyboard: false, title: route.hidden_endpoints ? 'Route shown from here' : 'Start', interactive: false }).addTo(map)
    L.marker([last.lat, last.lon], { icon: pin('is-finish', '■'), keyboard: false, title: route.hidden_endpoints ? 'Route shown to here' : 'Finish', interactive: false }).addTo(map)
    for (const k of route.km_markers ?? []) {
      L.marker([k.lat, k.lon], {
        icon: L.divIcon({ className: 'map-km', html: `<span>${k.km}</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
        keyboard: false,
        interactive: false,
      }).addTo(map)
    }
    map.on('click', (e: L.LeafletMouseEvent) => setSelected(nearestIndex(points, e.latlng.lat, e.latlng.lng)))
    mapRef.current = map
    // The sheet animates in; size the map after it settles.
    const t = setTimeout(() => map.invalidateSize(), 320)
    return () => {
      clearTimeout(t)
      map.remove()
      mapRef.current = null
      lineLayer.current = null
      dotRef.current = null
    }
  }, [points, route.km_markers, route.hidden_endpoints, route.start, route.finish])

  // Coloured route: casing + same-colour runs of segments as one polyline each.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    lineLayer.current?.remove()
    const group = L.layerGroup()
    // A dark 1-px outline under a 5-px line: readable on light tiles and the dark theme's.
    L.polyline(points.map((p) => [p.lat, p.lon] as [number, number]), { color: OUTLINE, weight: 7, opacity: 0.9, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(group)
    let run: Array<[number, number]> = []
    let color: string | null = null
    const flush = () => {
      if (run.length > 1) L.polyline(run, { color: color ?? cssVar('--faint', '#a3abb7'), weight: 5, opacity: 1, lineCap: 'round', lineJoin: 'round', interactive: false }).addTo(group)
    }
    points.forEach((p, i) => {
      const c = colorOf(p) ?? cssVar('--faint', '#a3abb7')
      if (c !== color && run.length) {
        run.push([p.lat, p.lon])
        flush()
        run = [run[run.length - 1]]
      }
      if (!run.length || i === 0) run = [[p.lat, p.lon]]
      else run.push([p.lat, p.lon])
      color = c
    })
    flush()
    group.addTo(map)
    lineLayer.current = group
    dotRef.current?.bringToFront()
  }, [points, colorOf])

  // Selected point → dot on the map.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (selected == null) { dotRef.current?.remove(); dotRef.current = null; return }
    const p = points[selected]
    if (!p) return
    if (!dotRef.current) {
      dotRef.current = L.circleMarker([p.lat, p.lon], { radius: 8, color: '#ffffff', weight: 3, fillColor: '#101418', fillOpacity: 1, interactive: false }).addTo(map)
    } else dotRef.current.setLatLng([p.lat, p.lon])
  }, [selected, points])

  const sel = selected != null ? points[selected] : null
  const modes = [
    hasPace && { value: 'pace', label: 'Pace' },
    hasHr && { value: 'hr', label: 'HR' },
    hasKind && { value: 'runwalk', label: 'Run/walk' },
  ].filter(Boolean) as Array<{ value: Mode; label: string }>

  return (
    <div className="route-map">
      {modes.length > 1 && <RangeSwitch compact value={mode} onChange={setMode} options={modes} label="Colour the route by" />}
      <div className="route-map-canvas" ref={host} role="region" aria-label="Route map. Tap the route to see pace and heart rate at that point." />
      {legend.kind === 'scale' ? (
        <div className="route-legend route-scale" role="img" aria-label={`Colour scale from ${legend.low.toLowerCase()} (blue) to ${legend.high.toLowerCase()} (red)`}>
          <span title={legend.lowTitle}>{legend.low}</span>
          <span className="route-scale-bar" aria-hidden="true">{legend.colors.map((c) => <i key={c} style={{ background: c }} />)}</span>
          <span title={legend.highTitle}>{legend.high}</span>
        </div>
      ) : (
        <div className="route-legend" aria-label="Legend">
          {legend.items.map((l) => (
            <span key={l.label}><i style={{ background: l.color }} />{l.label}</span>
          ))}
        </div>
      )}
      <p className="route-readout" aria-live="polite">
        {sel ? (
          <>
            <b>{kmText(sel.dist_m)}</b>
            {sel.pace_s_per_km != null && <> · {pace(sel.pace_s_per_km)} /km</>}
            {sel.hr != null && <> · {Math.round(sel.hr)} bpm</>}
            {sel.ele_m != null && <> · {Math.round(sel.ele_m)} m</>}
            {sel.segment === 'walk' && <> · walking</>}
          </>
        ) : (
          <span className="muted">Tap the route or the profile to see pace and heart rate there.</span>
        )}
      </p>
      {/* Only an older server that can't send the full route yet still trims it here. */}
      {route.hidden_endpoints && <p className="muted small">The first and last {route.trimmed_m || 200} m aren’t drawn yet.</p>}
      <ElevationProfile points={points} selected={selected} onSelect={setSelected} gain={route.elevation?.gain_m ?? null} />
    </div>
  )
}
