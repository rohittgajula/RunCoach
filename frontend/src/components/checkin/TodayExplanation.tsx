import { useEffect } from 'react'
import { useExplainToday } from '../../lib/queries'
import type { TodayCheckin } from '../../lib/types'

/** One generation per day per page load, however many cards mount. */
const requested = new Set<string>()

/** The lazy one-line "why" (POST /today/explain/), generated the first time it's seen. */
export function TodayExplanation({ today }: { today: TodayCheckin }) {
  const explain = useExplainToday()
  const ready = today.explanation?.status === 'ready' && !!today.explanation.text
  const { mutate } = explain

  useEffect(() => {
    if (ready || requested.has(today.date)) return
    requested.add(today.date)
    mutate()
  }, [ready, today.date, mutate])

  if (ready) return <p className="today-why">{today.explanation!.text}</p>
  if (explain.isPending) return <p className="today-why thinking-line">Working out why…</p>
  return null
}
