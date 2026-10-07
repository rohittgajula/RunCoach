import { createContext, useContext } from 'react'

export type RangeValue = { range: string; setRange: (r: string) => void }

/** The Health header's range switch, scoped to the section on screen. */
export const RangeContext = createContext<RangeValue>({ range: '4w', setRange: () => {} })

export function useHealthRange<T extends string>(): [T, (r: T) => void] {
  const { range, setRange } = useContext(RangeContext)
  return [range as T, setRange as (r: T) => void]
}
