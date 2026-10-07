import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { BottomSheet } from '../BottomSheet'
import { CloseIcon, ShareIcon } from '../Icons'
import { Skeleton } from '../States'
import { renderShareCard, shareFileName, type ShareCard } from './shareRender'

/**
 * Preview first, then share. With Web Share (files) the PNG goes to the system share
 * sheet; otherwise the image opens full-screen with "long-press to save".
 */
export default function ShareSheet({ card, open, onClose }: { card: ShareCard; open: boolean; onClose: () => void }) {
  const [blob, setBlob] = useState<Blob | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [full, setFull] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    let made: string | null = null
    setError('')
    renderShareCard(card)
      .then((b) => {
        if (!alive) return
        made = URL.createObjectURL(b)
        setBlob(b)
        setUrl(made)
      })
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : 'Could not draw the image.'))
    return () => {
      alive = false
      if (made) URL.revokeObjectURL(made)
      setBlob(null)
      setUrl(null)
    }
    // The card object is rebuilt by callers on each render; its JSON is the identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, JSON.stringify(card)])

  const share = async () => {
    if (!blob) return
    const file = new File([blob], shareFileName(card), { type: 'image/png' })
    const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean }
    if (nav.share && nav.canShare?.({ files: [file] })) {
      setBusy(true)
      try {
        await nav.share({ files: [file] })
        onClose()
      } catch (e) {
        // AbortError = the athlete closed the share sheet; nothing to say.
        if (!(e instanceof DOMException && e.name === 'AbortError')) setFull(true)
      } finally {
        setBusy(false)
      }
      return
    }
    setFull(true)
  }

  return (
    <>
      <BottomSheet open={open && !full} onClose={onClose} title="Share">
        <div className="share-sheet stack">
          {error ? (
            <p className="bad small">{error}</p>
          ) : url ? (
            <img className="share-preview" src={url} alt="Preview of the image you are about to share" />
          ) : (
            <Skeleton height={360} />
          )}
          <p className="muted small">Only what you see on the card is shared — no health details, no start or finish point.</p>
          <button type="button" className="btn btn-primary btn-block" disabled={!blob || busy} onClick={share}>
            <ShareIcon size={18} /> {busy ? 'Opening…' : 'Share image'}
          </button>
        </div>
      </BottomSheet>
      {full && url && createPortal(
        <div className="share-full" role="dialog" aria-modal="true" aria-label="Share image">
          <button type="button" className="chip share-full-close" aria-label="Close" onClick={() => { setFull(false); onClose() }}>
            <CloseIcon />
          </button>
          <img src={url} alt="Your share card" />
          <p>Long-press the image to save or share it.</p>
        </div>,
        document.body,
      )}
    </>
  )
}
