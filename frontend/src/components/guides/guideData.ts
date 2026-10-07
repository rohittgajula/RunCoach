import type { GuideKey } from '../../lib/types'

export type GuideMeta = { key: GuideKey; title: string; short: string; blurb: string; color: string }

export const GUIDES: GuideMeta[] = [
  { key: 'form', title: 'Form — how to land', short: 'Form', blurb: 'Land under your hips, quicker steps, a cadence metronome.', color: 'var(--accent)' },
  { key: 'breathing', title: 'Breathing', short: 'Breathing', blurb: 'Rhythms by effort and a calm breathing pacer.', color: 'var(--ok)' },
  { key: 'strength', title: 'Strength & drills', short: 'Strength', blurb: '8 moves, 2× a week, ~20 min — with a circuit timer.', color: 'var(--extra)' },
  { key: 'fueling', title: 'Fueling', short: 'Fueling', blurb: 'What to eat and drink before, during and after.', color: 'var(--warn)' },
  { key: 'warmup', title: 'Warm-up & cool-down', short: 'Warm-up', blurb: 'Ten minutes either side of a run, step by step.', color: 'var(--hard)' },
]

export const guideMeta = (key: string | null | undefined) => GUIDES.find((g) => g.key === key) ?? null

export const isGuideKey = (key: string | null | undefined): key is GuideKey => !!guideMeta(key)

export const guideHref = (key: GuideKey) => `/insights/guides?g=${key}`

/**
 * Which guide a focus item (Insights or Progress) points at, if any. Keys first, then
 * the words in the title — the focus keys are free-form strings on the server.
 */
const RULES: Array<[RegExp, GuideKey]> = [
  [/cadence|stride|overstrid|form|landing|ground.?contact|oscillation/i, 'form'],
  [/smok|breath|respirat|drift|lung/i, 'breathing'],
  [/run.?fraction|run.?walk|walk.?break|continuous|strength|drill|injur|knee|calf/i, 'strength'],
  [/fuel|hydrat|heat|hot|carb|gel|long.?run|water|electrolyt/i, 'fueling'],
  [/warm.?up|cool.?down|stiff|mobility/i, 'warmup'],
]

export function guideFor(item: { key?: string | null; title?: string | null }): GuideKey | null {
  const key = item.key ?? ''
  if (key === 'smoke_free') return 'breathing'
  for (const [re, guide] of RULES) if (re.test(key)) return guide
  const title = item.title ?? ''
  for (const [re, guide] of RULES) if (re.test(title)) return guide
  return null
}
