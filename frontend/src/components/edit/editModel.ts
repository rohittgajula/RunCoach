/**
 * R16 §A step editor model (lazy chunk only).
 *
 * The editor works on blocks: a single step, or a repeat group ("3 × (3:00 run + 1:00
 * walk)") edited as one. `fromWorkout` folds the stored flat step list into blocks
 * (the server folds repeats in GET /workouts/{id}/edit/), `toFlat` unfolds them for the
 * live bar preview, and `toApi` writes the PATCH body (docs/API_NOTES.md "R16 §A").
 */
import type { Intensity, Step } from '../../lib/types'
import type { EditItem, EditKind, EditStep } from '../../lib/r16'

export type Target =
  | { type: 'auto' }
  | { type: 'none' }
  | { type: 'hr'; low: number; high: number }
  | { type: 'pace'; low: number; high: number }

export type EStep = {
  uid: string
  kind: EditKind
  duration_s: number
  target: Target
  note: string
  /** Kept from the stored step so an untouched step draws the same colour. */
  intensity?: Intensity
}

export type Block =
  | { uid: string; type: 'step'; step: EStep }
  | { uid: string; type: 'repeat'; count: number; steps: EStep[] }

export const KINDS: Array<{ kind: EditKind; label: string }> = [
  { kind: 'warmup', label: 'Warm-up' },
  { kind: 'run', label: 'Run' },
  { kind: 'walk', label: 'Walk' },
  { kind: 'recovery', label: 'Recovery' },
  { kind: 'cooldown', label: 'Cool-down' },
  { kind: 'strides', label: 'Strides' },
  { kind: 'other', label: 'Other' },
]
export const kindLabel = (k: EditKind) => KINDS.find((x) => x.kind === k)?.label ?? k

export const MIN_STEP_S = 10
export const MAX_STEP_S = 90 * 60
export const MIN_TOTAL_S = 5 * 60
export const MAX_TOTAL_S = 240 * 60
export const MAX_REPEAT = 30

let seq = 0
export const uid = () => `u${++seq}`

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
export const clampStep = (s: number) => clamp(Math.round(s), MIN_STEP_S, MAX_STEP_S)

function eStep(s: EditStep): EStep {
  const hr = s.hr_low != null || s.hr_high != null
  const pace = s.pace_low != null || s.pace_high != null
  const type = s.target ?? (hr ? 'hr' : pace ? 'pace' : 'auto')
  const target: Target =
    type === 'hr' && hr ? { type: 'hr', low: s.hr_low ?? s.hr_high ?? 0, high: s.hr_high ?? s.hr_low ?? 0 }
      : type === 'pace' && pace ? { type: 'pace', low: s.pace_low ?? s.pace_high ?? 0, high: s.pace_high ?? s.pace_low ?? 0 }
        : type === 'none' ? { type: 'none' } : { type: 'auto' }
  return { uid: uid(), kind: s.kind, duration_s: Math.round(s.duration_s), target, note: s.note ?? '', intensity: s.intensity }
}

/** GET /workouts/{id}/edit/ `steps` → blocks. */
export function fromItems(items: EditItem[]): Block[] {
  return items.map((it): Block =>
    'repeat' in it
      ? { uid: uid(), type: 'repeat', count: it.repeat, steps: it.steps.map(eStep) }
      : { uid: uid(), type: 'step', step: eStep(it) })
}

/** The server's default intensity per kind (API_NOTES R16 §A). */
const INTENSITY: Record<EditKind, Intensity> = {
  warmup: 'walk', run: 'easy', walk: 'walk', recovery: 'walk', cooldown: 'walk', strides: 'hard', other: 'easy',
}

/** Bar colour: kept from the stored step unless the kind changed; HR targets near the top read harder. */
function intensityOf(s: EStep, ceiling: number | null): Intensity {
  if (s.intensity) return s.intensity
  if (s.kind === 'run' && s.target.type === 'hr' && ceiling && s.target.low > ceiling) return 'hard'
  return INTENSITY[s.kind]
}

const STORED_KIND: Record<EditKind, Step['kind']> = {
  warmup: 'warmup', run: 'run', walk: 'walk', recovery: 'recovery', cooldown: 'cooldown', strides: 'stride', other: 'interval',
}

function flatStep(s: EStep, ceiling: number | null): Step {
  return {
    kind: STORED_KIND[s.kind],
    duration_s: s.duration_s,
    intensity: intensityOf(s, ceiling),
    label: kindLabel(s.kind),
    hr_min: s.target.type === 'hr' ? s.target.low : null,
    hr_max: s.target.type === 'hr' ? s.target.high : null,
    pace_min_s: s.target.type === 'pace' ? s.target.low : null,
    pace_max_s: s.target.type === 'pace' ? s.target.high : null,
  }
}

/** Blocks → flat steps for WorkoutBar (the live preview). */
export function toFlat(blocks: Block[], ceiling: number | null = null): Step[] {
  const out: Step[] = []
  for (const b of blocks) {
    if (b.type === 'step') out.push(flatStep(b.step, ceiling))
    else for (let i = 0; i < b.count; i++) for (const s of b.steps) out.push(flatStep(s, ceiling))
  }
  return out
}

export const blockSeconds = (b: Block) =>
  b.type === 'step' ? b.step.duration_s : b.count * b.steps.reduce((t, s) => t + s.duration_s, 0)

export const totalSeconds = (blocks: Block[]) => blocks.reduce((t, b) => t + blockSeconds(b), 0)

const isRunKind = (k: EditKind) => k === 'run' || k === 'strides' || k === 'other'

export const runSeconds = (blocks: Block[]) =>
  blocks.reduce((t, b) => t + (b.type === 'step'
    ? (isRunKind(b.step.kind) ? b.step.duration_s : 0)
    : b.count * b.steps.reduce((u, s) => u + (isRunKind(s.kind) ? s.duration_s : 0), 0)), 0)

function apiStep(s: EStep): EditStep {
  return {
    kind: s.kind,
    duration_s: s.duration_s,
    ...(s.intensity ? { intensity: s.intensity } : {}),
    target: s.target.type,
    ...(s.target.type === 'hr' ? { hr_low: s.target.low, hr_high: s.target.high } : {}),
    ...(s.target.type === 'pace' ? { pace_low: s.target.low, pace_high: s.target.high } : {}),
    ...(s.note.trim() ? { note: s.note.trim() } : {}),
  }
}

/** Blocks → PATCH `steps` (a 1 × group is sent as plain steps). */
export function toApi(blocks: Block[]): EditItem[] {
  return blocks.flatMap((b): EditItem[] =>
    b.type === 'step' ? [apiStep(b.step)]
      : b.count >= 2 ? [{ repeat: b.count, steps: b.steps.map(apiStep) }]
        : b.steps.map(apiStep))
}

export const stepCount = (blocks: Block[]) => blocks.reduce((n, b) => n + (b.type === 'step' ? 1 : b.count * b.steps.length), 0)

export const signature = (blocks: Block[]) => JSON.stringify(toApi(blocks))

// --- edits ---------------------------------------------------------------------------

export function newStep(kind: EditKind): EStep {
  const duration: Record<EditKind, number> = {
    warmup: 300, run: 300, walk: 60, recovery: 90, cooldown: 300, strides: 20, other: 120,
  }
  return { uid: uid(), kind, duration_s: duration[kind], target: { type: 'auto' }, note: '' }
}

export const cloneStep = (s: EStep): EStep => ({ ...s, uid: uid(), target: { ...s.target } })

export function cloneBlock(b: Block): Block {
  return b.type === 'step'
    ? { uid: uid(), type: 'step', step: cloneStep(b.step) }
    : { uid: uid(), type: 'repeat', count: b.count, steps: b.steps.map(cloneStep) }
}

/** Where a new step goes: warm-up first, cool-down last, the rest before the cool-down. */
export function insertNew(blocks: Block[], block: Block): Block[] {
  const kind = block.type === 'step' ? block.step.kind : null
  if (kind === 'warmup') return [block, ...blocks]
  if (kind === 'cooldown') return [...blocks, block]
  const last = blocks[blocks.length - 1]
  if (last && last.type === 'step' && last.step.kind === 'cooldown') return [...blocks.slice(0, -1), block, last]
  return [...blocks, block]
}

export function newRepeat(): Block {
  return { uid: uid(), type: 'repeat', count: 3, steps: [{ ...newStep('run'), duration_s: 180 }, newStep('walk')] }
}

export function move<T>(list: T[], index: number, by: number): T[] {
  const to = index + by
  if (to < 0 || to >= list.length) return list
  const next = [...list]
  const [item] = next.splice(index, 1)
  next.splice(to, 0, item)
  return next
}

/**
 * ±minutes on the main running part: the longest single run step; with only repeat
 * groups, the run group gains/loses whole repetitions.
 */
export function addMinutes(blocks: Block[], minutes: number): Block[] {
  const delta = minutes * 60
  let best = -1
  let bestS = -1
  blocks.forEach((b, i) => {
    if (b.type === 'step' && b.step.kind === 'run' && b.step.duration_s > bestS) { best = i; bestS = b.step.duration_s }
  })
  if (best >= 0 && bestS + delta >= MIN_STEP_S) {
    return blocks.map((b, i) => (i === best && b.type === 'step' ? { ...b, step: { ...b.step, duration_s: clampStep(b.step.duration_s + delta) } } : b))
  }
  const g = blocks.findIndex((b) => b.type === 'repeat' && b.steps.some((s) => s.kind === 'run'))
  if (g >= 0) {
    const b = blocks[g] as Extract<Block, { type: 'repeat' }>
    const per = b.steps.reduce((t, s) => t + s.duration_s, 0) || 60
    const reps = Math.max(1, Math.round(Math.abs(delta) / per)) * Math.sign(delta)
    const count = clamp(b.count + reps, 1, MAX_REPEAT)
    return blocks.map((x, i) => (i === g ? { ...b, count } : x))
  }
  if (delta > 0) return insertNew(blocks, { uid: uid(), type: 'step', step: { ...newStep('run'), duration_s: delta } })
  return blocks
}

/**
 * Walk breaks: every single run step longer than one cycle becomes
 * N × (run + walk) with any remainder as a last run.
 */
export function addWalkBreaks(blocks: Block[], runS: number, walkS: number): Block[] {
  const out: Block[] = []
  for (const b of blocks) {
    if (b.type !== 'step' || b.step.kind !== 'run' || b.step.duration_s < runS + walkS) {
      out.push(b)
      continue
    }
    const cycles = Math.floor(b.step.duration_s / (runS + walkS))
    const rest = b.step.duration_s - cycles * (runS + walkS)
    const run = { ...b.step, uid: uid(), duration_s: runS, intensity: undefined }
    out.push({ uid: uid(), type: 'repeat', count: cycles, steps: [run, { ...newStep('walk'), duration_s: walkS }] })
    if (rest >= MIN_STEP_S) out.push({ uid: uid(), type: 'step', step: { ...cloneStep(b.step), duration_s: rest } })
  }
  return out
}

/** Same HR range on every run step (inside groups too). */
export function setRunHr(blocks: Block[], low: number, high: number): Block[] {
  const set = (s: EStep): EStep => (s.kind === 'run' ? { ...s, target: { type: 'hr', low, high } } : s)
  return blocks.map((b) => (b.type === 'step' ? { ...b, step: set(b.step) } : { ...b, steps: b.steps.map(set) }))
}

export const hasRunStep = (blocks: Block[]) =>
  blocks.some((b) => (b.type === 'step' ? b.step.kind === 'run' : b.steps.some((s) => s.kind === 'run')))

/** "3 × (3:00 run + 1:00 walk)" */
export function repeatText(b: Extract<Block, { type: 'repeat' }>, withCount = true): string {
  const inner = b.steps.map((s) => `${mmss(s.duration_s)} ${kindLabel(s.kind).toLowerCase()}`).join(' + ')
  const group = b.steps.length > 1 ? `(${inner})` : inner
  return withCount ? `${b.count} × ${group}` : group
}

/** 75 → "1:15", 20 → "0:20", 3725 → "1:02:05" */
export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`
}

/** "3", "3:30", "90s", "1:02:00", "45 s", "4m" → seconds (null when unreadable). */
export function parseDuration(text: string): number | null {
  const t = text.trim().toLowerCase().replace(/\s+/g, '')
  if (!t) return null
  let m = /^(\d{1,2}):(\d{1,2}):(\d{2})$/.exec(t)
  if (m) return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])
  m = /^(\d{1,3}):(\d{1,2})$/.exec(t)
  if (m) return Number(m[1]) * 60 + Number(m[2])
  m = /^(\d+(?:\.\d+)?)(s|sec)$/.exec(t)
  if (m) return Math.round(Number(m[1]))
  m = /^(\d+(?:\.\d+)?)(m|min)?$/.exec(t)
  if (m) return Math.round(Number(m[1]) * 60)
  return null
}
