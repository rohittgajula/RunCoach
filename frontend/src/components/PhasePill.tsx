import type { PhaseKind } from '../lib/types'

const LABEL: Record<PhaseKind, string> = {
  base: 'Base', build: 'Build', peak: 'Peak', taper: 'Taper', recovery: 'Recovery', race: 'Race',
}

/** Base blue · Build green · Peak orange · Taper purple · Recovery grey · Race red. */
export function PhasePill({ kind, name }: { kind: PhaseKind; name?: string }) {
  return <span className={`phase-pill phase-${kind}`}>{name && name.length <= 14 ? name : LABEL[kind] ?? kind}</span>
}

export const phaseLabel = (kind: PhaseKind) => LABEL[kind] ?? kind
