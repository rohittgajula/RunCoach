/**
 * The report's "Keep logging — still needed: a (needs …); b (needs …)." finding as a
 * short, collapsible checklist with progress, instead of one long grey sentence.
 */
type Need = { label: string; progress: string | null; done: number; of: number }

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

function parseNeed(raw: string): Need {
  const open = raw.indexOf(' (')
  const label = cap((open < 0 ? raw : raw.slice(0, open)).trim())
  const detail = open < 0 ? '' : raw.slice(open + 2).replace(/\)\s*$/, '')
  let m: RegExpMatchArray | null
  // "needs 5 mornings after smoking and 5 without; you have 0 and 1"
  if ((m = detail.match(/needs (\d+) mornings after (.+?) and \d+ without(?:; you have (\d+) and (\d+))?/))) {
    const n = +m[1]
    const a = +(m[3] ?? 0)
    const b = +(m[4] ?? 0)
    return { label, progress: `${Math.min(a, n)}/${n} mornings after ${m[2]} · ${Math.min(b, n)}/${n} without`, done: Math.min(a, n) + Math.min(b, n), of: 2 * n }
  }
  // "needs 3 runs the day after smoking and 3 after other days; you have 1 and 4"
  if ((m = detail.match(/needs (\d+) runs the day after (.+?) and \d+ after other days; you have (\d+) and (\d+)/))) {
    const n = +m[1]
    const a = +m[3]
    const b = +m[4]
    return { label: 'Next-day runs', progress: `${Math.min(a, n)}/${n} runs after ${m[2]} · ${Math.min(b, n)}/${n} after other days`, done: Math.min(a, n) + Math.min(b, n), of: 2 * n }
  }
  // dose / timing: "needs 4 nights each of|with X and Y; you have 1 and 2"
  if ((m = detail.match(/needs (\d+) nights each (?:of|with) (.+?) and (.+?); you have (\d+) and (\d+)/))) {
    const n = +m[1]
    const a = Math.min(+m[4], n)
    const b = Math.min(+m[5], n)
    return { label, progress: `${a}/${n} nights ${m[2]} · ${b}/${n} ${m[3]}`, done: a + b, of: 2 * n }
  }
  // "needs 4 tracked weeks with morning data; you have 2"
  if ((m = detail.match(/needs (\d+) tracked weeks.*?; you have (\d+)/))) {
    const n = +m[1]
    const a = Math.min(+m[2], n)
    return { label, progress: `${a}/${n} weeks`, done: a, of: n }
  }
  if (/^needs a week of tracking/.test(detail)) return { label, progress: 'A week of logs in this range and the one before', done: 0, of: 0 }
  return { label, progress: detail ? cap(detail.replace(/^needs /, '')) : null, done: 0, of: 0 }
}

export function parseNeeds(text: string): Need[] {
  const body = text.replace(/^.*?still needed:\s*/i, '').replace(/\.\s*$/, '')
  if (body === text) return []
  // Split on "; " only outside parentheses (the details contain their own "; ").
  const parts: string[] = []
  let depth = 0
  let cur = ''
  for (let i = 0; i < body.length; i++) {
    const c = body[i]
    if (c === '(') depth++
    if (c === ')') depth = Math.max(0, depth - 1)
    if (c === ';' && depth === 0) {
      parts.push(cur.trim())
      cur = ''
      continue
    }
    cur += c
  }
  if (cur.trim()) parts.push(cur.trim())
  return parts.map(parseNeed)
}

export function NeedsChecklist({ text }: { text: string }) {
  const needs = parseNeeds(text)
  if (!needs.length) return <p className="muted small">{text}</p>
  return (
    <details className="needs">
      <summary>
        <span>Keep logging</span>
        <span className="muted small">{needs.length} {needs.length === 1 ? 'thing' : 'things'} still to unlock</span>
      </summary>
      <ul className="needs-list">
        {needs.map((n) => (
          <li key={n.label}>
            <span className="needs-label">{n.label}</span>
            {n.progress && <span className="muted small">{n.progress}</span>}
            {n.of > 0 && (
              <span className="needs-bar" aria-hidden="true">
                <span style={{ transform: `scaleX(${Math.min(1, n.done / n.of)})` }} />
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}
