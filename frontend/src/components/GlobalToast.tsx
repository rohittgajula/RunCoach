import { useEffect, useSyncExternalStore } from 'react'
import { Link } from 'react-router-dom'

/**
 * R17: an app-wide toast for actions whose screen closes as they finish (deleting an
 * activity). `showToast('Run deleted', {to: '/me/deleted', label: 'Deleted activities'})`.
 */
type Toast = { id: number; text: string; link?: { to: string; label: string } }
let current: Toast | null = null
const subs = new Set<() => void>()
const emit = () => subs.forEach((f) => f())

export function showToast(text: string, link?: Toast['link']) {
  current = { id: Date.now(), text, link }
  emit()
}

export function GlobalToast() {
  const t = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f) }, () => current)
  useEffect(() => {
    if (!t) return
    const timer = setTimeout(() => { if (current?.id === t.id) { current = null; emit() } }, 6000)
    return () => clearTimeout(timer)
  }, [t])
  if (!t) return null
  return (
    <div className="toast toast-link" role="status">
      <span>{t.text}</span>
      {t.link && <Link to={t.link.to} onClick={() => { current = null; emit() }}>{t.link.label}</Link>}
    </div>
  )
}
