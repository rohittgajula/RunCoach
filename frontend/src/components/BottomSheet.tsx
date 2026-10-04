import { useEffect, useRef, useState, type ReactNode, type PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { ChipButton } from './ChipButton'
import { CloseIcon } from './Icons'

/**
 * Bottom sheet: drag handle (pull down to dismiss), close X chip, optional title and
 * action chips. `full` makes it cover the screen (chat list, settings, memory).
 */
export function BottomSheet({
  open, onClose, title, actions, full = false, children, footer, label,
}: {
  open: boolean
  onClose: () => void
  title?: ReactNode
  actions?: ReactNode
  full?: boolean
  children: ReactNode
  footer?: ReactNode
  label?: string
}) {
  const [drag, setDrag] = useState(0)
  const start = useRef<number | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  useEffect(() => {
    if (!open) setDrag(0)
  }, [open])

  if (!open) return null

  const down = (event: PointerEvent) => {
    start.current = event.clientY
    ;(event.target as Element).setPointerCapture?.(event.pointerId)
  }
  const move = (event: PointerEvent) => {
    if (start.current == null) return
    setDrag(Math.max(0, event.clientY - start.current))
  }
  const up = () => {
    if (start.current == null) return
    start.current = null
    if (drag > 110) onClose()
    else setDrag(0)
  }

  return createPortal(
    <div className="sheet-root" role="presentation">
      <div className="sheet-backdrop" onClick={onClose} style={{ opacity: Math.max(0, 1 - drag / 400) }} />
      <div
        className={`sheet ${full ? 'sheet-full' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={label ?? (typeof title === 'string' ? title : undefined)}
        style={drag ? { transform: `translateY(${drag}px)`, transition: 'none' } : undefined}
      >
        <div
          className="sheet-grip"
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={up}
          onPointerCancel={up}
        >
          <span className="sheet-handle" />
        </div>
        <div className="sheet-header">
          <ChipButton label="Close" onClick={onClose}>
            <CloseIcon />
          </ChipButton>
          <div className="sheet-title">{title}</div>
          <div className="sheet-actions">{actions}</div>
        </div>
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
