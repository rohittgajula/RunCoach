import type { ProgressFocus as Focus } from '../../lib/types'

export function ProgressFocus({ focus }: { focus: Focus[] }) {
  if (!focus?.length) return null
  return (
    <ol className="focus">
      {focus.map((item, i) => (
        <li key={item.key ?? i} className="focus-item">
          <span className={`focus-num ${item.kind === 'check' ? 'is-check' : ''}`}>{i + 1}</span>
          <div className="grow">
            <p className="focus-title">{item.title}</p>
            {item.why && <p className="muted small">{item.why}</p>}
            {item.how && <p className="focus-how">{item.how}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
