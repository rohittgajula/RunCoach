import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { RefreshIcon } from '../components/Icons'
import { fullSync } from './r18'

/**
 * Pull-to-refresh on touch devices: pull down from the very top past 72 px and release.
 * Ignores sheets/dialogs, horizontal swipes and pages not scrolled to the top.
 */
export default function PullToRefresh() {
  const client = useQueryClient()
  const [pull, setPull] = useState(0)
  const start = useRef<{ x: number; y: number } | null>(null)
  const dist = useRef(0)
  useEffect(() => {
    const down = (e: TouchEvent) => {
      const t = e.target as Element | null
      if (window.scrollY > 0 || e.touches.length !== 1 || t?.closest('[role="dialog"], .sheet, .bottom-sheet, input, textarea, select')) return
      start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }
    }
    const move = (e: TouchEvent) => {
      if (!start.current) return
      const dy = e.touches[0].clientY - start.current.y
      const dx = Math.abs(e.touches[0].clientX - start.current.x)
      if (dy <= 0 || dx > dy || window.scrollY > 0) { start.current = null; dist.current = 0; setPull(0); return }
      dist.current = Math.min(110, dy * 0.5)
      setPull(dist.current)
    }
    const up = () => {
      if (start.current && dist.current >= 72) void fullSync(client).catch(() => {})
      start.current = null
      dist.current = 0
      setPull(0)
    }
    window.addEventListener('touchstart', down, { passive: true })
    window.addEventListener('touchmove', move, { passive: true })
    window.addEventListener('touchend', up)
    window.addEventListener('touchcancel', up)
    return () => {
      window.removeEventListener('touchstart', down)
      window.removeEventListener('touchmove', move)
      window.removeEventListener('touchend', up)
      window.removeEventListener('touchcancel', up)
    }
  }, [client])
  if (pull < 8) return null
  return (
    <div className="ptr" style={{ transform: `translate(-50%, ${pull - 44}px)` }} aria-hidden="true">
      <RefreshIcon className={pull >= 72 ? 'ptr-ready' : ''} />
    </div>
  )
}

