import { Link } from 'react-router-dom'
import { guideFor, guideHref } from './guideData'

/** "Open guide ›" under a focus item that matches one of the guides. */
export function GuideLink({ item }: { item: { key?: string | null; title?: string | null } }) {
  const key = guideFor(item)
  if (!key) return null
  return (
    <Link className="guide-link" to={guideHref(key)}>
      Open guide ›
    </Link>
  )
}
