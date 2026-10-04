import type { ReactNode } from 'react'

export function Loading({ label = 'Loading…', block = false }: { label?: string; block?: boolean }) {
  return (
    <div className={`state state-loading ${block ? 'state-block' : ''}`} role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

/** Shimmer placeholders while a card's data arrives. */
export function Skeleton({ lines = 3, height }: { lines?: number; height?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {height ? (
        <div className="skeleton-block" style={{ height }} />
      ) : (
        Array.from({ length: lines }, (_, i) => (
          <div key={i} className="skeleton-line" style={{ width: `${90 - i * 15}%` }} />
        ))
      )}
    </div>
  )
}

export function Empty({
  icon, title, children, action,
}: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state state-empty">
      {icon && <div className="state-icon">{icon}</div>}
      <p className="state-title">{title}</p>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p className="state-title">Couldn't load this</p>
      <p className="muted">{message ?? 'Check your connection and try again.'}</p>
      {onRetry && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}
