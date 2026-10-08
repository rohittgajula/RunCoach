import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/AuthContext'

/**
 * R10 design kit: topic rings, tone chips (better/worse = colour AND ▲/▼), status pills,
 * metric tiles, "then → now" rows, target bars and the avatar that opens Me.
 * Colour by topic, never for good/bad.
 */

export type Topic = 'run' | 'recovery' | 'sleep' | 'habits' | 'fuel'
export type ToneKind = 'good' | 'bad' | 'flat' | 'info'

export const topicColor = (t: Topic) => `var(--${t})`

/** Score ring: value out of `max` (default 100), topic colour, number in the middle. */
export function TopicRing({
  value, max = 100, topic, size = 96, stroke = 12, display, label, sub,
}: {
  value: number | null | undefined
  max?: number
  topic: Topic
  size?: number
  stroke?: number
  /** What to print in the middle (defaults to the rounded value). */
  display?: ReactNode
  /** Accessible name, e.g. "Readiness". */
  label: string
  sub?: string
}) {
  const r = 60 - stroke / 2 - 6
  const c = 2 * Math.PI * r
  const has = value != null && Number.isFinite(value)
  const share = has ? Math.max(0, Math.min(1, (value as number) / max)) : 0
  const shown = display ?? (has ? Math.round(value as number) : '--')
  return (
    <svg
      className="topic-ring"
      viewBox="0 0 120 120"
      width={size}
      height={size}
      role="img"
      aria-label={has ? `${label} ${Math.round(value as number)}${max === 100 ? ' of 100' : ''}` : `${label}: no data`}
    >
      <circle cx="60" cy="60" r={r} fill="none" stroke={`var(--${topic}-tint)`} strokeWidth={stroke} />
      {has && share > 0 && (
        <circle
          className="topic-ring-fill"
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke={topicColor(topic)}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${(c * share).toFixed(1)} ${c.toFixed(1)}`}
          transform="rotate(-90 60 60)"
        />
      )}
      <text x="60" y={sub ? 62 : 69} textAnchor="middle" className="topic-ring-value" fontSize={sub ? 26 : 30}>
        {shown}
      </text>
      {sub && (
        <text x="60" y="82" textAnchor="middle" className="topic-ring-sub" fontSize="12">
          {sub}
        </text>
      )}
    </svg>
  )
}

/** Small rounded chip; tone = better (green) / worse (red) / steady (grey) / info. */
export function ToneChip({ tone = 'flat', children, title }: { tone?: ToneKind; children: ReactNode; title?: string }) {
  return (
    <span className={`tone-chip is-${tone}`} title={title}>
      {children}
    </span>
  )
}

/**
 * ▲ 4 ms / ▼ 2 bpm / — steady. `better` says which direction is good for the reader;
 * null colours it grey whichever way it moved.
 */
export function Delta({
  value, better, format = (v) => String(Math.round(v)), unit = '', flatWithin = 0, steadyText = 'steady', suffix,
}: {
  value: number | null | undefined
  better: 'higher' | 'lower' | null
  format?: (v: number) => string
  unit?: string
  flatWithin?: number
  steadyText?: string
  suffix?: string
}) {
  if (value == null || !Number.isFinite(value)) return null
  const flat = Math.abs(value) <= flatWithin || format(Math.abs(value)) === format(0)
  if (flat) return <ToneChip tone="flat">— {steadyText}</ToneChip>
  const up = value > 0
  const tone: ToneKind = better == null ? 'flat' : (up === (better === 'higher')) ? 'good' : 'bad'
  const word = tone === 'good' ? 'better' : tone === 'bad' ? 'worse' : 'changed'
  return (
    <span className={`tone-chip is-${tone}`} aria-label={`${up ? 'up' : 'down'} ${format(Math.abs(value))}${unit ? ` ${unit}` : ''}, ${word}`}>
      <span aria-hidden="true">{up ? '▲' : '▼'}</span>
      {format(Math.abs(value))}
      {unit && ` ${unit}`}
      {suffix && ` ${suffix}`}
    </span>
  )
}

/** Inline coloured arrow (no chip): for "then → now" rows and small captions. */
export function Arrow({ value, better }: { value: number | null | undefined; better: 'higher' | 'lower' | null }) {
  if (value == null || !Number.isFinite(value) || value === 0) return <span className="arrow is-flat" aria-label="no change">—</span>
  const up = value > 0
  const tone = better == null ? 'flat' : up === (better === 'higher') ? 'good' : 'bad'
  return (
    <span className={`arrow is-${tone}`} aria-label={`${up ? 'up' : 'down'}${tone === 'good' ? ', better' : tone === 'bad' ? ', worse' : ''}`}>
      {up ? '▲' : '▼'}
    </span>
  )
}

export type StatusKind = 'improving' | 'worsening' | 'steady' | 'not_enough_data' | 'need_more_data' | null | undefined

const STATUS_WORD: Record<string, string> = {
  improving: 'Improving',
  worsening: 'Worsening',
  steady: 'Steady',
  not_enough_data: 'Need more data',
  need_more_data: 'Need more data',
}

/** Improving (green) · Worsening (red) · Steady (ink) · Need more data (grey). */
export function StatusPill({ status, children }: { status: StatusKind; children?: ReactNode }) {
  const key = status ?? 'not_enough_data'
  const cls = key === 'improving' ? 'is-improving' : key === 'worsening' ? 'is-worsening' : key === 'steady' ? 'is-steady' : 'is-none'
  return <span className={`status-pill ${cls}`}>{children ?? STATUS_WORD[key] ?? 'Need more data'}</span>
}

/** A labelled pill for free-form states (training status, "Zones updated", "Hot"). */
export function Pill({ topic, solid = false, children }: { topic?: Topic | 'ok' | 'bad' | 'ink'; solid?: boolean; children: ReactNode }) {
  return <span className={`pill ${topic ? `pill-${topic}` : ''} ${solid ? 'is-solid' : ''}`}>{children}</span>
}

/**
 * Metric tile (2-col grids): label + chip, big number, a small chart/line under it.
 * `info` = an (i) button next to the label; on a tappable tile the tap target is a
 * full-size button underneath it, so the two buttons are never nested.
 */
export function MetricTile({
  label, value, unit, chip, sub, children, onClick, className = '', info, labelSuffix,
}: {
  label: string
  /** R16 §C: "· yesterday" when the value isn't today's. */
  labelSuffix?: ReactNode
  value: ReactNode
  unit?: string
  chip?: ReactNode
  sub?: ReactNode
  children?: ReactNode
  onClick?: () => void
  className?: string
  info?: ReactNode
}) {
  const body = (
    <>
      <span className="mt-head">
        <span className="mt-label">
          <span className="lbl">{label}{labelSuffix}</span>
          {info}
        </span>
        {chip}
      </span>
      <span className="mt-value">
        {value}
        {unit && <small> {unit}</small>}
      </span>
      {sub && <span className="mt-sub">{sub}</span>}
      {children}
    </>
  )
  if (onClick && info) {
    return (
      <div className={`mt is-tappable has-hit ${className}`}>
        <button type="button" className="mt-hit" aria-label={`${label}: open chart`} onClick={onClick} />
        {body}
      </div>
    )
  }
  return onClick ? (
    <button type="button" className={`mt is-tappable ${className}`} onClick={onClick}>
      {body}
    </button>
  ) : (
    <div className={`mt ${className}`}>{body}</div>
  )
}

export type ThenNowRow = { label: string; then: string; now: string; delta?: number | null; better?: 'higher' | 'lower' | null; unit?: string }

/** "HRV  41 → 45 ms ▲" */
export function ThenNow({ rows }: { rows: ThenNowRow[] }) {
  if (!rows.length) return null
  return (
    <dl className="then-now">
      {rows.map((r) => (
        <div key={r.label}>
          <dt>{r.label}</dt>
          <dd>
            {r.then} → {r.now}
            {r.unit && ` ${r.unit}`} {r.delta !== undefined && <Arrow value={r.delta} better={r.better ?? null} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** Horizontal bar with an optional light "target range" band behind it. */
export function TargetBar({
  value, max, low, high, topic = 'run', label,
}: { value: number | null | undefined; max: number; low?: number | null; high?: number | null; topic?: Topic; label: string }) {
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / (max || 1)) * 100))}%`
  return (
    <div className="target-bar" role="img" aria-label={label}>
      {low != null && high != null && (
        <span className="target-band" style={{ left: pct(low), width: `calc(${pct(high)} - ${pct(low)})`, background: `var(--${topic}-soft, var(--${topic}-tint))` }} />
      )}
      {value != null && <span className="target-fill" style={{ width: pct(value), background: topicColor(topic) }} />}
    </div>
  )
}

/** Simple progress bar (fuel, water, shoes). */
export function Meter({ value, max, topic, label, over = false }: { value: number; max: number; topic: Topic; label: string; over?: boolean }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100))
  return (
    <div className="meter" style={{ background: `var(--${topic}-tint)` }} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={Math.round(max)} aria-valuenow={Math.round(value)}>
      <span style={{ width: `${pct}%`, background: over ? 'var(--bad)' : topicColor(topic) }} />
    </div>
  )
}

/** Card heading row: 16/800 title + optional right side (chip, pill, link). */
export function CardHead({ title, aside, sub }: { title: ReactNode; aside?: ReactNode; sub?: ReactNode }) {
  return (
    <div className="kit-head">
      <div className="grow">
        <h2 className="kit-title">{title}</h2>
        {sub && <p className="kit-sub">{sub}</p>}
      </div>
      {aside}
    </div>
  )
}

export function initialOf(name: string | null | undefined): string {
  const n = (name ?? '').trim()
  return n ? n[0].toUpperCase() : 'R'
}

/** Top-right avatar on Today and every page header → Me. */
export function AvatarButton() {
  const { athlete, username } = useAuth()
  const navigate = useNavigate()
  return (
    <button type="button" className="avatar-btn" aria-label="Me: profile, settings, shoes, reminders, badges" onClick={() => navigate('/me')}>
      {initialOf(athlete?.display_name || username)}
    </button>
  )
}
