/** Findings / highlights: one line each with a coloured dot (good · bad · neutral). */
export function Bullets({ items }: { items: Array<{ tone?: string | null; text: string }> }) {
  if (!items.length) return null
  return (
    <ul className="bullets">
      {items.map((h, i) => (
        <li key={i} className={`bullet is-${h.tone ?? 'neutral'}`}>
          <span className="bullet-dot" aria-hidden="true" />
          <span>{h.text}</span>
        </li>
      ))}
    </ul>
  )
}
