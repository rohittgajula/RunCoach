import { lazy, Suspense, useState } from 'react'
import { ShareIcon } from '../Icons'
import type { ShareCard } from './shareRender'

// The canvas renderer and sheet only load when someone taps Share.
const ShareSheet = lazy(() => import('./ShareSheet'))

/** "Share" chip/button → preview sheet. `card` is built lazily so callers stay cheap. */
export function ShareButton({
  card, label = 'Share', variant = 'chip', disabled = false, className = '',
}: { card: () => ShareCard | null; label?: string; variant?: 'chip' | 'button'; disabled?: boolean; className?: string }) {
  const [open, setOpen] = useState<ShareCard | null>(null)
  const go = () => {
    const c = card()
    if (c) setOpen(c)
  }
  return (
    <>
      {variant === 'chip' ? (
        <button type="button" className={`chip ${className}`} aria-label={label} title={label} onClick={go} disabled={disabled}>
          <ShareIcon />
        </button>
      ) : (
        <button type="button" className={`btn btn-secondary btn-sm share-btn ${className}`} onClick={go} disabled={disabled}>
          <ShareIcon size={16} /> {label}
        </button>
      )}
      {open && (
        <Suspense fallback={null}>
          <ShareSheet card={open} open onClose={() => setOpen(null)} />
        </Suspense>
      )}
    </>
  )
}
