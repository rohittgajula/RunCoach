import type { ReactNode } from 'react'

export function Logo() {
  return (
    <span className="logo" aria-label="RunCoach">
      Run<span className="logo-accent">Coach</span>
    </span>
  )
}

/** Sticky header: chips left, logo (or title) centre, chips right. */
export function PageHeader({ left, right, title }: { left?: ReactNode; right?: ReactNode; title?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header-side">{left}</div>
      <div className="page-header-title">{title ?? <Logo />}</div>
      <div className="page-header-side page-header-right">{right}</div>
    </header>
  )
}
