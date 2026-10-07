import { dur } from '../../lib/format'

/** Seconds → "1h 5m" / "40m". */
export const hm = (s: number | null | undefined) => (s == null ? '—' : dur(s))
/** 12,345 */
export const n0 = (v: number | null | undefined) => (v == null ? '—' : Math.round(v).toLocaleString())
export const pctOf = (p: number | null | undefined) => (p == null ? '' : `${Math.round(p)}%`)
export const stressWord = (v: number) => (v <= 25 ? 'rest' : v <= 50 ? 'low' : v <= 75 ? 'medium' : 'high')
