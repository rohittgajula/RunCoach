import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft } from './Icons'
import { AvatarButton } from './Kit'

export function Logo() {
  return (
    <span className="logo" aria-label="RunCoach">
      Run<span className="logo-accent">Coach</span>
    </span>
  )
}

/**
 * R10 sticky header: [left chips] big left-aligned title · [right controls] · avatar → Me.
 * `back` shows a back chevron instead (Me and its sub-pages, which are not tabs).
 */
export function PageHeader({
  left, right, title, back, avatar = true, sub,
}: { left?: ReactNode; right?: ReactNode; title?: ReactNode; back?: string | true; avatar?: boolean; sub?: ReactNode }) {
  const navigate = useNavigate()
  return (
    <header className="page-header">
      {back && (
        <button
          type="button"
          className="chip chip-plain"
          aria-label="Back"
          onClick={() => (back === true ? navigate(-1) : navigate(back))}
        >
          <ChevronLeft />
        </button>
      )}
      {left && <div className="page-header-side">{left}</div>}
      <div className="page-header-title">
        {sub && <span className="lbl">{sub}</span>}
        <h1 className="page-title">{title ?? <Logo />}</h1>
      </div>
      {right && <div className="page-header-side page-header-right">{right}</div>}
      {avatar && <AvatarButton />}
    </header>
  )
}
