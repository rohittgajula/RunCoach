import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { useAuth } from '../../../lib/AuthContext'
import { useActivityDetail, useActivityRoute } from '../../../lib/queries'
import { useShareData, type ShareData } from '../../../lib/r15'
import type { ActivityCard } from '../../../lib/types'
import { BottomSheet } from '../../BottomSheet'
import { ChevronDown, DownloadIcon, ShareIcon } from '../../Icons'
import { Segmented } from '../../settings/Segmented'
import { Skeleton } from '../../States'
import '../../../styles/r15.css'
import { bestKm, fileSlug, saveBlob, shownRoute, splitsFromRoute, toCsv, toGpx } from './studioData'
import {
  DEFAULT_FIELDS, FIELD_LABEL, SIZES, autoText, drawStudio, exportPng, hasField,
  type Background, type Field, type LayoutKey, type Photo, type SizeKey, type StudioData, type StudioOptions, type WeightKey,
} from './studioRender'

const STORE = 'rc.shareStudio.v1'
const DEFAULTS: StudioOptions = {
  bg: 'transparent', solid: '#101418', fields: DEFAULT_FIELDS, splitsStyle: 'bars', routeColor: '#2f6bff',
  textColor: 'auto', size: 'story', layout: 'bottom', weight: 'bold', photoFit: 'cover', darken: 0.3,
}

function loadOpts(): StudioOptions {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) || 'null') as Partial<StudioOptions> | null
    if (!raw) return DEFAULTS
    // Keep the saved order, add any field a newer build introduced, drop unknown ones.
    const known = new Set(DEFAULT_FIELDS.map((f) => f.key))
    const saved = (raw.fields ?? []).filter((f) => known.has(f.key))
    const fields = [...saved, ...DEFAULT_FIELDS.filter((f) => !saved.some((s) => s.key === f.key))]
    // A photo is never stored, so don't come back to an empty "photo" background.
    return { ...DEFAULTS, ...raw, fields, bg: raw.bg === 'photo' ? 'transparent' : raw.bg ?? DEFAULTS.bg }
  } catch {
    return DEFAULTS
  }
}

const dateLabel = (iso: string) => new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })

function weatherText(w: ShareData['weather']): string | null {
  if (!w || w.temp_c == null) return null
  const parts = [`${Math.round(w.temp_c)}°C`]
  if (w.feels_like_c != null && Math.abs(w.feels_like_c - w.temp_c) >= 2) parts.push(`feels ${Math.round(w.feels_like_c)}°`)
  if (w.humidity != null) parts.push(`${Math.round(w.humidity)}% humidity`)
  return parts.join(' · ')
}

function fromShareData(s: ShareData): StudioData {
  const splits = s.splits.map((p) => ({
    km: p.km,
    distance_m: p.distance_m,
    pace_s_per_km: p.pace_s,
    split_s: p.partial ? Math.round((p.pace_s * p.distance_m) / 1000) : p.pace_s,
    avg_hr: p.hr,
  }))
  return {
    title: s.workout_title || s.title,
    date: dateLabel(s.started_at || s.date),
    distance_m: s.distance_m,
    duration_s: s.moving_s || s.elapsed_s,
    pace_s_per_km: s.avg_pace_s_per_km ?? s.run_pace_s_per_km,
    avg_hr: s.avg_hr,
    max_hr: s.max_hr,
    elevation_gain_m: s.elevation_gain_m,
    cadence_spm: s.cadence_spm,
    calories: s.calories,
    weather: weatherText(s.weather),
    splits,
    best_km: s.best_km ? { km: s.best_km.km, split_s: s.best_km.pace_s } : null,
    route: s.route.available && s.route.points.length > 1 ? s.route.points : null,
  }
}

const SWATCHES = ['#101418', '#ffffff', '#2f6bff', '#f26b3a', '#0e9f9a', '#7a5af8']
const ROUTE_SWATCHES = ['#2f6bff', '#f26b3a', '#ffffff', '#101418', '#0e9f9a', '#f2a516']

/**
 * R15 share studio: route + stats on a transparent, solid, photo or map background, drawn
 * on a canvas at full resolution. Choices are remembered on this device; a photo never is
 * (and never leaves the device).
 */
export default function ShareStudio({ activity, open, onClose }: { activity: ActivityCard; open: boolean; onClose: () => void }) {
  const { athlete } = useAuth()
  const hideEnds = athlete?.map_hide_endpoints ?? true
  const share = useShareData(activity.id)
  // Older backends: build the same picture from the route + detail the run sheet uses.
  const legacy = share.isSuccess && share.data === null
  const route = useActivityRoute(legacy || share.isError ? activity.id : null)
  const detail = useActivityDetail(legacy || share.isError ? activity.id : null)

  const data: StudioData | null = useMemo(() => {
    if (share.data) return fromShareData(share.data)
    if (!(legacy || share.isError) || route.isPending) return null
    const r = route.data
    const splits = r?.available ? splitsFromRoute(r.points, activity.distance_m, activity.duration_s) : []
    const actual = detail.data?.actual
    return {
      title: activity.name || 'Run',
      date: dateLabel(activity.start),
      distance_m: activity.distance_m,
      duration_s: activity.duration_s,
      pace_s_per_km: activity.distance_m > 0 ? activity.duration_s / (activity.distance_m / 1000) : null,
      avg_hr: detail.data?.avg_hr ?? null,
      max_hr: detail.data?.max_hr ?? null,
      elevation_gain_m: r?.elevation?.gain_m ?? null,
      cadence_spm: actual?.avg_cadence_spm ?? null,
      calories: null,
      weather: null,
      splits,
      best_km: bestKm(splits),
      route: shownRoute(r, hideEnds),
    }
  }, [share.data, share.isError, legacy, route.isPending, route.data, detail.data, activity, hideEnds])

  const [opts, setOpts] = useState<StudioOptions>(loadOpts)
  const [title, setTitle] = useState<string | null>(null)
  const [tab, setTab] = useState<'bg' | 'fields' | 'style' | 'data'>('bg')
  const [photo, setPhoto] = useState<Photo | null>(null)
  const [busy, setBusy] = useState<'' | 'png' | 'share'>('')
  const [msg, setMsg] = useState('')
  const [tilesFailed, setTilesFailed] = useState(false)
  const [redraw, setRedraw] = useState(0)
  const tiles = useRef(new Map<string, HTMLImageElement | null>())
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    try { localStorage.setItem(STORE, JSON.stringify(opts)) } catch { /* private mode */ }
  }, [opts])
  const set = useCallback(<K extends keyof StudioOptions>(k: K, v: StudioOptions[K]) => setOpts((o) => ({ ...o, [k]: v })), [])

  const card: StudioData | null = useMemo(() => (data ? { ...data, title: title ?? data.title } : null), [data, title])
  const mapAllowed = !!card?.route

  // Live preview (half resolution), redrawn on the next frame after any change.
  useEffect(() => {
    if (!card || !canvas.current) return
    let alive = true
    const raf = requestAnimationFrame(() => {
      if (!canvas.current) return
      const r = drawStudio(canvas.current, card, opts, opts.size === 'landscape' ? 0.4 : 0.5, photo, tiles.current)
      setTilesFailed(r.tilesFailed)
      r.tilesPending?.then(() => alive && setRedraw((n) => n + 1))
    })
    return () => { alive = false; cancelAnimationFrame(raf) }
  }, [card, opts, photo, redraw])

  // Fonts may land after the first draw.
  useEffect(() => {
    const f = (document as Document & { fonts?: FontFaceSet }).fonts
    f?.ready.then(() => setRedraw((n) => n + 1)).catch(() => undefined)
  }, [])

  // Photo: decoded locally, never uploaded.
  const pickPhoto = (file: File | undefined) => {
    if (!file) return
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      setPhoto({ img, w: img.naturalWidth, h: img.naturalHeight, ox: 0, oy: 0 })
      set('bg', 'photo')
    }
    img.onerror = () => setMsg('That file could not be opened as an image.')
    img.src = url
  }

  const drag = useRef<{ x: number; y: number } | null>(null)
  const onDown = (e: RPointerEvent<HTMLCanvasElement>) => {
    if (opts.bg !== 'photo' || !photo) return
    drag.current = { x: e.clientX, y: e.clientY }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onMove = (e: RPointerEvent<HTMLCanvasElement>) => {
    if (!drag.current || !photo) return
    const rect = e.currentTarget.getBoundingClientRect()
    const { w: W, h: H } = SIZES[opts.size]
    const s = opts.photoFit === 'cover' ? Math.max(W / photo.w, H / photo.h) : Math.min(W / photo.w, H / photo.h)
    const freeX = Math.abs(W - photo.w * s)
    const freeY = Math.abs(H - photo.h * s)
    const dx = ((e.clientX - drag.current.x) * W) / rect.width
    const dy = ((e.clientY - drag.current.y) * H) / rect.height
    drag.current = { x: e.clientX, y: e.clientY }
    // Cover: dragging right shows more of the left (offset moves with the finger).
    const clamp = (v: number) => Math.max(-1, Math.min(1, v))
    setPhoto({ ...photo, ox: freeX > 1 ? clamp(photo.ox + (2 * dx) / freeX) : 0, oy: freeY > 1 ? clamp(photo.oy + (2 * dy) / freeY) : 0 })
  }
  const onUp = () => { drag.current = null }

  const slug = card ? fileSlug(card.title, share.data?.date ?? activity.start.slice(0, 10)) : 'runcoach'
  const makePng = () => exportPng(card!, opts, opts.bg === 'photo' ? photo : null, tiles.current)

  const download = async () => {
    if (!card) return
    setBusy('png')
    setMsg('')
    try {
      saveBlob(await makePng(), `${slug}.png`)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Could not make the image.')
    } finally {
      setBusy('')
    }
  }
  const nav = navigator as Navigator & { canShare?: (d: ShareData_) => boolean }
  const canShareFiles = typeof nav.share === 'function' && typeof nav.canShare === 'function'
  const shareIt = async () => {
    if (!card) return
    setBusy('share')
    setMsg('')
    try {
      const file = new File([await makePng()], `${slug}.png`, { type: 'image/png' })
      if (nav.canShare?.({ files: [file] })) await nav.share({ files: [file] })
      else {
        saveBlob(file, file.name)
        setMsg('Sharing images isn’t supported here, so it was downloaded instead.')
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) setMsg(e instanceof Error ? e.message : 'Could not share.')
    } finally {
      setBusy('')
    }
  }

  const moveField = (i: number, dir: -1 | 1) =>
    setOpts((o) => {
      const j = i + dir
      if (j < 0 || j >= o.fields.length) return o
      const f = [...o.fields]
      ;[f[i], f[j]] = [f[j], f[i]]
      return { ...o, fields: f }
    })
  const toggleField = (key: Field['key']) => setOpts((o) => ({ ...o, fields: o.fields.map((f) => (f.key === key ? { ...f, on: !f.on } : f)) }))

  const size = SIZES[opts.size]
  const textAuto = card ? autoText({ ...opts, textColor: 'auto' }) : '#fff'

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      full
      title="Share run"
      footer={
        <div className="studio-actions">
          <button type="button" className="btn btn-secondary btn-grow" disabled={!card || !!busy} onClick={download}>
            <DownloadIcon size={18} /> {busy === 'png' ? 'Drawing…' : 'Download PNG'}
          </button>
          {canShareFiles && (
            <button type="button" className="btn btn-primary btn-grow" disabled={!card || !!busy} onClick={shareIt}>
              <ShareIcon size={18} /> {busy === 'share' ? 'Opening…' : 'Share'}
            </button>
          )}
        </div>
      }
    >
      <div className="studio">
        <div className={`studio-preview ${opts.bg === 'transparent' ? 'is-checker' : ''}`}>
          {card ? (
            <canvas
              ref={canvas}
              className={`studio-canvas ${opts.bg === 'photo' && photo ? 'is-draggable' : ''}`}
              style={{ aspectRatio: `${size.w} / ${size.h}` }}
              role="img"
              aria-label={`Preview, ${size.label} ${size.w}×${size.h}`}
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onUp}
            />
          ) : share.isError && route.isError ? (
            <p className="bad small">Could not load this run.</p>
          ) : (
            <Skeleton height={320} />
          )}
        </div>
        {opts.bg === 'photo' && photo && <p className="muted small studio-hint">Drag the preview to move your photo.</p>}
        {tilesFailed && opts.bg === 'map' && <p className="bad small studio-hint">Some map tiles didn’t load. Try again, or pick another background.</p>}
        {msg && <p className="small studio-hint" role="status">{msg}</p>}

        <div className="segmented segmented-full studio-tabs" role="tablist" aria-label="Share options">
          {([['bg', 'Background'], ['fields', 'Fields'], ['style', 'Style'], ['data', 'Data']] as const).map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={`segmented-option ${tab === k ? 'is-active' : ''}`} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>

        {tab === 'bg' && (
          <div className="stack">
            <div className="studio-choices" role="radiogroup" aria-label="Background">
              {([
                ['transparent', 'Transparent', 'PNG with see-through background — lay it over your own photo or story.'],
                ['solid', 'Solid colour', 'A plain colour behind the route and stats.'],
                ['photo', 'Your photo', 'Pick a photo on this device. It is never uploaded.'],
                ...(mapAllowed ? [['map', 'Map', 'OpenStreetMap tiles under the route. Shows where you ran.']] : []),
              ] as Array<[Background, string, string]>).map(([k, l, d]) => (
                <button key={k} type="button" role="radio" aria-checked={opts.bg === k} className={`studio-choice ${opts.bg === k ? 'is-active' : ''}`}
                  onClick={() => (k === 'photo' && !photo ? document.getElementById('studio-photo')?.click() : set('bg', k))}>
                  <span className={`studio-swatch bg-${k}`} style={k === 'solid' ? { background: opts.solid } : undefined} aria-hidden="true" />
                  <span className="grow"><b>{l}</b><span className="muted small block">{d}</span></span>
                </button>
              ))}
            </div>
            <input id="studio-photo" type="file" accept="image/*" hidden onChange={(e) => { pickPhoto(e.target.files?.[0]); e.target.value = '' }} />
            {opts.bg === 'solid' && (
              <ColorRow label="Background colour" value={opts.solid} swatches={SWATCHES} onChange={(v) => set('solid', v)} />
            )}
            {opts.bg === 'photo' && photo && (
              <section className="card stack-sm">
                <Segmented label="Photo fit" value={opts.photoFit} onChange={(v) => { set('photoFit', v); setPhoto({ ...photo, ox: 0, oy: 0 }) }}
                  options={[{ value: 'cover', label: 'Fill (crop)' }, { value: 'contain', label: 'Fit whole photo' }]} />
                <label className="studio-slider">
                  <span>Darken <b>{Math.round(opts.darken * 100)}%</b></span>
                  <input type="range" min={0} max={0.8} step={0.05} value={opts.darken} onChange={(e) => set('darken', Number(e.target.value))} />
                </label>
                <div className="row-wrap">
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => document.getElementById('studio-photo')?.click()}>Change photo</button>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPhoto({ ...photo, ox: 0, oy: 0 })}>Re-centre</button>
                </div>
              </section>
            )}
            {opts.bg === 'map' && (
              <p className="notice small">A map shows where you ran{hideEnds ? ' (start and finish are still cut off)' : ''}. Map data © OpenStreetMap contributors is printed on the image.</p>
            )}
          </div>
        )}

        {tab === 'fields' && (
          <div className="stack">
            <label className="field-label studio-title-input">
              Title
              <input value={card ? card.title : ''} maxLength={60} onChange={(e) => setTitle(e.target.value)} placeholder="Morning run" />
            </label>
            <section className="card studio-fields" aria-label="Fields on the image">
              {opts.fields.map((f, i) => {
                const avail = card ? hasField(card, f.key) || f.key === 'title' : true
                const off = opts.layout === 'minimal' && f.key !== 'route' && f.key !== 'brand'
                return (
                  <div key={f.key} className={`studio-field ${!avail || off ? 'is-na' : ''}`}>
                    <span className="grow">
                      <b>{FIELD_LABEL[f.key]}</b>
                      {!avail && <span className="muted small block">No data for this run</span>}
                      {avail && off && <span className="muted small block">Hidden in the Minimal layout</span>}
                    </span>
                    <button type="button" className="chip" aria-label={`Move ${FIELD_LABEL[f.key]} up`} disabled={i === 0} onClick={() => moveField(i, -1)}>
                      <ChevronDown className="flip" />
                    </button>
                    <button type="button" className="chip" aria-label={`Move ${FIELD_LABEL[f.key]} down`} disabled={i === opts.fields.length - 1} onClick={() => moveField(i, 1)}>
                      <ChevronDown />
                    </button>
                    <button type="button" role="switch" aria-checked={f.on} aria-label={FIELD_LABEL[f.key]} className={`switch ${f.on ? 'is-on' : ''}`} onClick={() => toggleField(f.key)} />
                  </div>
                )
              })}
            </section>
            {opts.fields.some((f) => f.key === 'splits' && f.on) && (
              <Segmented label="Splits style" value={opts.splitsStyle} onChange={(v) => set('splitsStyle', v)}
                options={[{ value: 'bars', label: 'Bar strip' }, { value: 'table', label: 'Mini table' }]} />
            )}
            <p className="muted small">The order here is the order on the image. Top/Bottom layouts keep the route on its own side.</p>
            <button type="button" className="link-btn small" onClick={() => set('fields', DEFAULT_FIELDS)}>Reset fields</button>
          </div>
        )}

        {tab === 'style' && (
          <div className="stack">
            <section className="card stack-sm">
              <h3 className="studio-h">Size</h3>
              <Segmented<SizeKey> label="Size" value={opts.size} onChange={(v) => set('size', v)}
                options={(Object.keys(SIZES) as SizeKey[]).map((k) => ({ value: k, label: SIZES[k].label }))} />
              <p className="muted small">{size.w} × {size.h} px</p>
            </section>
            <section className="card stack-sm">
              <h3 className="studio-h">Layout</h3>
              <Segmented<LayoutKey> label="Layout" value={opts.layout} onChange={(v) => set('layout', v)}
                options={[{ value: 'bottom', label: 'Stats below' }, { value: 'top', label: 'Stats above' }, { value: 'stacked', label: 'Stacked' }, { value: 'minimal', label: 'Route only' }]} />
            </section>
            <section className="card stack-sm">
              <ColorRow label="Route colour" value={opts.routeColor} swatches={ROUTE_SWATCHES} onChange={(v) => set('routeColor', v)} />
            </section>
            <section className="card stack-sm">
              <ColorRow
                label="Text colour"
                value={opts.textColor === 'auto' ? textAuto : opts.textColor}
                swatches={['#ffffff', '#101418']}
                onChange={(v) => set('textColor', v)}
                auto={{ on: opts.textColor === 'auto', set: () => set('textColor', 'auto') }}
              />
            </section>
            <section className="card stack-sm">
              <h3 className="studio-h">Text weight</h3>
              <Segmented<WeightKey> label="Text weight" value={opts.weight} onChange={(v) => set('weight', v)}
                options={[{ value: 'light', label: 'Light' }, { value: 'regular', label: 'Regular' }, { value: 'bold', label: 'Bold' }]} />
            </section>
            <button type="button" className="link-btn small" onClick={() => setOpts({ ...DEFAULTS, fields: opts.fields })}>Reset style</button>
          </div>
        )}

        {tab === 'data' && card && (
          <div className="stack">
            <section className="card stack-sm">
              <h3 className="studio-h">Route (GPX)</h3>
              <p className="muted small">
                {card.route ? `${card.route.length} points${hideEnds ? ' — start and finish cut off, as on your map' : ''}. Opens in Strava, Komoot, Google Earth and most map apps.` : 'This run has no GPS route.'}
              </p>
              <button type="button" className="btn btn-secondary" disabled={!card.route}
                onClick={() => saveBlob(new Blob([toGpx(card.title, share.data?.started_at ?? activity.start, legacy ? route.data : null, card.route!)], { type: 'application/gpx+xml' }), `${slug}.gpx`)}>
                <DownloadIcon size={18} /> Download GPX
              </button>
            </section>
            <section className="card stack-sm">
              <h3 className="studio-h">Km splits (CSV)</h3>
              <p className="muted small">{card.splits.length ? `${card.splits.length} splits: km, time, pace, elapsed, heart rate. Opens in any spreadsheet.` : 'No splits for this run.'}</p>
              <button type="button" className="btn btn-secondary" disabled={!card.splits.length}
                onClick={() => saveBlob(new Blob([toCsv(card.splits)], { type: 'text/csv' }), `${slug}-splits.csv`)}>
                <DownloadIcon size={18} /> Download CSV
              </button>
            </section>
          </div>
        )}
      </div>
    </BottomSheet>
  )
}

type ShareData_ = { files?: File[] }

function ColorRow({ label, value, swatches, onChange, auto }: {
  label: string; value: string; swatches: string[]; onChange: (v: string) => void; auto?: { on: boolean; set: () => void }
}) {
  return (
    <div className="stack-sm">
      <h3 className="studio-h">{label}</h3>
      <div className="studio-swatches" role="radiogroup" aria-label={label}>
        {auto && (
          <button type="button" role="radio" aria-checked={auto.on} className={`studio-auto ${auto.on ? 'is-active' : ''}`} onClick={auto.set}>Auto</button>
        )}
        {swatches.map((c) => (
          <button key={c} type="button" role="radio" aria-checked={!auto?.on && value.toLowerCase() === c} aria-label={c}
            className={`studio-dot ${!auto?.on && value.toLowerCase() === c ? 'is-active' : ''}`} style={{ background: c }} onClick={() => onChange(c)} />
        ))}
        <label className="studio-dot studio-pick" aria-label={`Custom ${label.toLowerCase()}`}>
          <input type="color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : '#2f6bff'} onChange={(e) => onChange(e.target.value)} />
        </label>
      </div>
    </div>
  )
}
