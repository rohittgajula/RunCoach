import { lazy, Suspense, useState } from 'react'
import { WindIcon } from '../Icons'

const CravingSheet = lazy(() => import('./CravingSheet'))

/** "Craving now" — opens the craving form + 3-minute breathing pacer. */
export function CravingButton({ className = '' }: { className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className={`craving-btn ${className}`} onClick={() => setOpen(true)}>
        <WindIcon size={16} /> Craving now
      </button>
      {open && (
        <Suspense fallback={null}>
          <CravingSheet onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
