import { Fragment, type ReactNode } from 'react'

/**
 * Small, safe Markdown → React. Everything becomes React text nodes; no HTML from
 * the model ever reaches the DOM. Supports headings, paragraphs with line breaks,
 * bullet/numbered lists (nested by indentation), **bold**, *italic*, `code`, and
 * horizontal rules. Anything else renders as plain text.
 */

const INLINE = /(\*\*[^*\n]+?\*\*|__[^_\n]+?__|\*[^*\s][^*\n]*?\*|_[^_\s][^_\n]*?_|`[^`\n]+`)/g

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let i = 0
  for (const match of text.matchAll(INLINE)) {
    const token = match[0]
    const at = match.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const key = `${keyBase}-${i++}`
    if (token.startsWith('**') || token.startsWith('__')) {
      out.push(<strong key={key}>{inline(token.slice(2, -2), key)}</strong>)
    } else if (token.startsWith('`')) {
      out.push(<code key={key}>{token.slice(1, -1)}</code>)
    } else {
      // Guard snake_case words: only treat _x_ as italic at word boundaries.
      const before = text[at - 1]
      if (token.startsWith('_') && before && /\w/.test(before)) out.push(token)
      else out.push(<em key={key}>{inline(token.slice(1, -1), key)}</em>)
    }
    last = at + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function withBreaks(lines: string[], key: string): ReactNode[] {
  return lines.map((line, i) => (
    <Fragment key={`${key}-${i}`}>
      {i > 0 && <br />}
      {inline(line, `${key}-${i}`)}
    </Fragment>
  ))
}

type ListItem = { text: string[]; children: ListNode | null }
type ListNode = { ordered: boolean; start: number; items: ListItem[]; indent: number }

const LIST_LINE = /^(\s*)([-*+•]|\d{1,3}[.)])\s+(.*)$/

function renderList(list: ListNode, key: string): ReactNode {
  const items = list.items.map((item, i) => (
    <li key={`${key}-${i}`}>
      {withBreaks(item.text, `${key}-${i}`)}
      {item.children && renderList(item.children, `${key}-${i}-c`)}
    </li>
  ))
  return list.ordered ? (
    <ol key={key} start={list.start !== 1 ? list.start : undefined}>{items}</ol>
  ) : (
    <ul key={key}>{items}</ul>
  )
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let paragraph: string[] = []
  let root: ListNode | null = null
  let stack: ListNode[] = []

  const flushParagraph = () => {
    if (paragraph.length) blocks.push(<p key={`p${blocks.length}`}>{withBreaks(paragraph, `p${blocks.length}`)}</p>)
    paragraph = []
  }
  const flushList = () => {
    if (root) blocks.push(renderList(root, `l${blocks.length}`))
    root = null
    stack = []
  }

  for (const raw of lines) {
    const line = raw.replace(/\t/g, '    ')
    if (!line.trim()) {
      flushParagraph()
      // A blank line inside a list is common in model output; keep the list open
      // and let a following non-list line close it.
      continue
    }

    const list = LIST_LINE.exec(line)
    if (list) {
      flushParagraph()
      const indent = list[1].length
      const ordered = /\d/.test(list[2])
      const start = ordered ? Number.parseInt(list[2], 10) : 1
      const item: ListItem = { text: [list[3]], children: null }

      if (!root) {
        root = { ordered, start, items: [item], indent }
        stack = [root]
        continue
      }
      let top = stack[stack.length - 1]
      while (stack.length > 1 && indent < top.indent) {
        stack.pop()
        top = stack[stack.length - 1]
      }
      if (indent > top.indent + 1 && top.items.length) {
        const parent = top.items[top.items.length - 1]
        const child: ListNode = { ordered, start, items: [item], indent }
        parent.children = child
        stack.push(child)
      } else {
        top.items.push(item)
      }
      continue
    }

    // Continuation line of a list item (indented, not a new bullet).
    if (root && /^\s{2,}\S/.test(line)) {
      const top = stack[stack.length - 1]
      top.items[top.items.length - 1].text.push(line.trim())
      continue
    }

    flushList()

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      flushParagraph()
      const level = Math.min(heading[1].length + 2, 6)
      const Tag = `h${level}` as 'h3' | 'h4' | 'h5' | 'h6'
      blocks.push(<Tag key={`h${blocks.length}`}>{inline(heading[2], `h${blocks.length}`)}</Tag>)
      continue
    }
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      flushParagraph()
      blocks.push(<hr key={`hr${blocks.length}`} />)
      continue
    }
    paragraph.push(line.trim())
  }
  flushParagraph()
  flushList()

  return <div className="md">{blocks}</div>
}
