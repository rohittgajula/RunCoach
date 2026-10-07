import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { reducedMotion } from '../lib/navMotion'
import { ChipButton } from './ChipButton'
import { CloseIcon } from './Icons'

const CLOSE_MS = 200
const DISMISS_PX = 110
const DISMISS_VELOCITY = 0.6 // px per ms — a flick closes it however short
const SLOP = 6

type Content = { title?: ReactNode; actions?: ReactNode; children: ReactNode; footer?: ReactNode }

/**
 * Bottom sheet: drag handle (pull down to dismiss), close X chip, optional title and
 * action chips. `full` makes it cover the screen (chat list, settings, memory).
 *
 * Smooth UI: slides in and out on the compositor (transform only), follows the finger
 * without re-rendering its content, closes on a flick as well as a long pull, can be
 * pulled down from the header or from content already scrolled to its top, and keeps
 * showing its last content while it slides away.
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
  const [mounted, setMounted] = useState(open)
  const [closing, setClosing] = useState(false)
  const sheet = useRef<HTMLDivElement>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  // What to keep showing while the sheet slides away (parents often clear it on close).
  const last = useRef<Content>({ title, actions, children, footer })
  if (open) last.current = { title, actions, children, footer }
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  // Open → mount; close → play the exit, then unmount.
  useLayoutEffect(() => {
    if (open) {
      setMounted(true)
      setClosing(false)
      // Reopened mid-exit after a pull: start from rest, not where the finger left it.
      if (sheet.current) sheet.current.style.transform = ''
      if (backdrop.current) backdrop.current.style.opacity = ''
      return
    }
    if (!mounted) return
    if (reducedMotion()) {
      setMounted(false)
      return
    }
    setClosing(true)
    const timer = setTimeout(() => {
      setMounted(false)
      setClosing(false)
    }, CLOSE_MS)
    return () => clearTimeout(timer)
    // `mounted` is read, not tracked: only `open` drives the exit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open])

  // --- drag, written straight to the DOM (no React render per pointer move) ---------
  const drag = useRef<{ y: number; t: number; dy: number; v: number; active: boolean; id: number } | null>(null)

  const place = (dy: number) => {
    const el = sheet.current
    if (!el) return
    el.style.transition = 'none'
    el.style.transform = dy > 0 ? `translate3d(0, ${dy}px, 0)` : ''
    if (backdrop.current) backdrop.current.style.opacity = String(Math.max(0, 1 - dy / 500))
  }
  const release = () => {
    const d = drag.current
    drag.current = null
    if (!d || !d.active) return
    const el = sheet.current
    if (d.dy > DISMISS_PX || (d.dy > 24 && d.v > DISMISS_VELOCITY)) {
      // Leave the sheet where the finger let go; the exit animation continues from there.
      if (el) el.style.transition = ''
      onCloseRef.current()
      return
    }
    if (el) {
      el.style.transition = ''
      el.style.transform = ''
    }
    if (backdrop.current) backdrop.current.style.opacity = ''
  }
  const moveTo = (y: number) => {
    const d = drag.current
    if (!d) return false
    const dy = Math.max(0, y - d.y)
    const now = performance.now()
    d.v = (dy - d.dy) / Math.max(1, now - d.t)
    d.t = now
    d.dy = dy
    if (!d.active && dy > SLOP) d.active = true
    if (d.active) place(dy)
    return d.active
  }

  // Grip + header: pointer events. Capture only once it is really a drag, so a tap on
  // the close chip or an action still lands on that button.
  const down = (event: PointerEvent) => {
    if (event.button !== 0) return
    drag.current = { y: event.clientY, t: performance.now(), dy: 0, v: 0, active: false, id: event.pointerId }
  }
  const move = (event: PointerEvent) => {
    const d = drag.current
    if (!d || d.id !== event.pointerId) return
    const wasActive = d.active
    if (moveTo(event.clientY) && !wasActive) (event.currentTarget as Element).setPointerCapture?.(event.pointerId)
  }

  // Content: a downward pull while it is scrolled to the top drags the sheet instead of
  // rubber-banding the list. Touch events, because the browser owns pointer events
  // once it starts a native scroll.
  useEffect(() => {
    const el = body.current
    if (!mounted || !el) return
    let startX = 0
    let candidate = false
    const skip = (target: EventTarget | null) =>
      target instanceof Element && !!target.closest('input, textarea, select, [contenteditable], .recharts-wrapper, [data-no-sheet-drag]')
    const onStart = (event: TouchEvent) => {
      const t = event.touches[0]
      candidate = event.touches.length === 1 && el.scrollTop <= 0 && !skip(event.target)
      if (!candidate) return
      startX = t.clientX
      drag.current = { y: t.clientY, t: performance.now(), dy: 0, v: 0, active: false, id: -1 }
    }
    const onMove = (event: TouchEvent) => {
      const d = drag.current
      if (!candidate || !d || d.id !== -1) return
      const t = event.touches[0]
      if (!d.active) {
        const dx = Math.abs(t.clientX - startX)
        const dy = t.clientY - d.y
        // Sideways or upward: an ordinary scroll, leave it alone.
        if (dy < 0 || dx > Math.abs(dy) || el.scrollTop > 0) {
          if (dy < 0 || dx > SLOP) { candidate = false; drag.current = null }
          return
        }
      }
      if (moveTo(t.clientY) && event.cancelable) event.preventDefault()
    }
    const onEnd = () => {
      if (drag.current?.id === -1) release()
      candidate = false
    }
    el.addEventListener('touchstart', onStart, { passive: true })
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('touchend', onEnd)
    el.addEventListener('touchcancel', onEnd)
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('touchcancel', onEnd)
    }
  }, [mounted])

  if (!mounted) return null
  const shown = open ? { title, actions, children, footer } : last.current

  return createPortal(
    <div className={`sheet-root ${closing ? 'is-closing' : ''}`} role="presentation">
      <div className="sheet-backdrop" ref={backdrop} onClick={onClose} />
      <div
        ref={sheet}
        className={`sheet ${full ? 'sheet-full' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={label ?? (typeof shown.title === 'string' ? shown.title : undefined)}
      >
        <div className="sheet-drag" onPointerDown={down} onPointerMove={move} onPointerUp={release} onPointerCancel={release}>
          <div className="sheet-grip">
            <span className="sheet-handle" />
          </div>
          <div className="sheet-header">
            <ChipButton label="Close" onClick={onClose}>
              <CloseIcon />
            </ChipButton>
            <div className="sheet-title">{shown.title}</div>
            <div className="sheet-actions">{shown.actions}</div>
          </div>
        </div>
        <div className="sheet-body" ref={body}>{shown.children}</div>
        {shown.footer && <div className="sheet-footer">{shown.footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
