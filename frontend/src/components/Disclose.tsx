import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BottomSheet } from './BottomSheet'
import { ChevronDown, ChevronRight } from './Icons'

/**
 * R14 §1 progressive disclosure: a screen opens with a short summary and the detail
 * lives behind a collapsed group, a "See details ›" sheet or a grouped list row.
 * Nothing is removed — every card is still one tap away.
 */

/** Collapsible detail group. Remembers open/closed per key for the session. */
export function Disclosure({
  title, sub, children, defaultOpen = false, id, className = '',
}: {
  title: ReactNode
  sub?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  /** Session memory key (e.g. "sleep-details"). */
  id?: string
  className?: string
}) {
  const [open, setOpenState] = useState<boolean>(() => {
    if (!id) return defaultOpen
    try {
      const v = sessionStorage.getItem(`rc.disc.${id}`)
      return v == null ? defaultOpen : v === '1'
    } catch {
      return defaultOpen
    }
  })
  const setOpen = (v: boolean) => {
    setOpenState(v)
    if (id) {
      try { sessionStorage.setItem(`rc.disc.${id}`, v ? '1' : '0') } catch { /* ignore */ }
    }
  }
  const bodyId = useId()
  return (
    <section className={`disclosure ${open ? 'is-open' : ''} ${className}`}>
      <button type="button" className="disclosure-head" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
        <span className="grow">
          <span className="disclosure-title">{title}</span>
          {sub && <span className="disclosure-sub">{sub}</span>}
        </span>
        <ChevronDown size={20} className="disclosure-chev" />
      </button>
      {open && <div id={bodyId} className="disclosure-body stack">{children}</div>}
    </section>
  )
}

/** A card of grouped list rows (Me, Overview links, More). */
export function RowGroup({ title, children }: { title?: ReactNode; children: ReactNode }) {
  return (
    <section className="row-group-wrap">
      {title && <h2 className="row-group-title">{title}</h2>}
      <div className="card row-group">{children}</div>
    </section>
  )
}

type RowProps = {
  icon?: ReactNode
  title: ReactNode
  sub?: ReactNode
  aside?: ReactNode
}

function RowBody({ icon, title, sub, aside }: RowProps) {
  return (
    <>
      {icon && <span className="row-icon" aria-hidden="true">{icon}</span>}
      <span className="grow row-text">
        <span className="row-title">{title}</span>
        {sub && <span className="row-sub">{sub}</span>}
      </span>
      {aside}
      <ChevronRight size={18} className="muted row-chev" />
    </>
  )
}

/** One row: a link (`to`) or a button (`onClick`). */
export function Row({ to, onClick, ...rest }: RowProps & { to?: string; onClick?: () => void }) {
  if (to) return <Link to={to} className="row"><RowBody {...rest} /></Link>
  return <button type="button" className="row" onClick={onClick}><RowBody {...rest} /></button>
}

/** A row whose detail is an existing card, shown in a sheet. */
export function SheetRow({ sheetTitle, children, ...rest }: RowProps & { sheetTitle?: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Row {...rest} onClick={() => setOpen(true)} />
      <BottomSheet open={open} onClose={() => setOpen(false)} title={sheetTitle ?? rest.title}>
        {open && <div className="stack sheet-cards">{children}</div>}
      </BottomSheet>
    </>
  )
}

/** "See details ›" text button that opens a sheet with the full content. */
export function SeeDetails({ label = 'See details', title, children, className = '' }: { label?: string; title: ReactNode; children: ReactNode; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className={`see-details ${className}`} onClick={() => setOpen(true)}>
        {label} <ChevronRight size={16} />
      </button>
      <BottomSheet open={open} onClose={() => setOpen(false)} title={title}>
        {open && <div className="stack sheet-cards">{children}</div>}
      </BottomSheet>
    </>
  )
}

/** Short summary header for a Health section: one sentence + up to 3 facts. */
export function SectionSummary({ title, facts, children }: { title: ReactNode; facts?: Array<ReactNode | null | false>; children?: ReactNode }) {
  const shown = (facts ?? []).filter(Boolean).slice(0, 3)
  return (
    <section className="card section-summary">
      <p className="section-summary-title">{title}</p>
      {shown.length > 0 && (
        <ul className="section-summary-facts">
          {shown.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}
      {children}
    </section>
  )
}
