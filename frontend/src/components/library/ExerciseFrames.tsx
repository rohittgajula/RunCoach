/**
 * The movement: animated where we have one, two poses where we do not.
 *
 * Three tiers of media exist and the component walks them best-first, so no
 * caller has to know which an exercise has:
 *
 *   anim     a real looping animation of the grey figure (30 exercises)
 *   classic  that same figure as start and peak stills
 *   flat     the flat illustration every exercise has
 *
 * The start/peak pair is cross-faded rather than cut between. The eye fills in
 * the middle the way it does for a flip-book, and a hard cut reads as a glitch.
 * A single-pose exercise — a stretch, a hold — simply shows its one picture;
 * animating a hold would be inventing movement that is not in it.
 */

import { useEffect, useState } from 'react'

export type Media = {
  best?: 'anim' | 'classic' | 'flat' | null
  anim?: string
  classic?: { start?: string; peak?: string; main?: string }
  flat?: { start?: string; peak?: string; main?: string }
}

const FRAME_MS = 1000

/** Best available: a real animation, else the nicest still pair we have. */
function pick(media: Media): { anim?: string; frames: string[] } {
  if (media.anim) return { anim: media.anim, frames: [] }
  for (const style of [media.classic, media.flat]) {
    if (!style) continue
    const frames = [style.start, style.peak].filter(Boolean) as string[]
    if (frames.length) return { frames }
    if (style.main) return { frames: [style.main] }
  }
  return { frames: [] }
}

export function ExerciseFrames({ media, name }: { media: Media; name: string }) {
  const { anim, frames } = pick(media)
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(true)

  useEffect(() => {
    if (anim || !playing || frames.length < 2) return
    const id = setInterval(() => setFrame((f) => (f + 1) % frames.length), FRAME_MS)
    return () => clearInterval(id)
  }, [anim, playing, frames.length])

  if (anim) {
    // An animated WebP plays itself; there is nothing to drive and nothing to
    // pause that would not mean decoding it by hand.
    return (
      <div className="exframes">
        <img src={anim} alt={`${name}, animated`} className="exframe is-on"
             loading="lazy" decoding="async" />
      </div>
    )
  }

  if (!frames.length) {
    return (
      <div className="exframes is-empty">
        <p className="muted small">No picture for this one.</p>
      </div>
    )
  }

  return (
    <div className="exframes">
      {frames.map((src, i) => (
        <img
          key={src}
          src={src}
          alt={frames.length > 1 && i === 0 ? `${name}, start` : `${name}, finish`}
          className={`exframe${i === frame ? ' is-on' : ''}`}
          loading="lazy"
          decoding="async"
        />
      ))}
      {frames.length > 1 && (
        <button type="button" className="exframes-toggle"
                aria-label={playing ? 'Pause' : 'Play'}
                onClick={() => setPlaying((p) => !p)}>
          {playing ? '❚❚' : '▶'}
        </button>
      )}
    </div>
  )
}

/** The small square on a grid card: one still, never animated. 708 looping
 *  animations on one screen would melt a phone. */
export function ExerciseThumb({ media, className }: { media: Media; className?: string }) {
  const style = media.flat ?? media.classic
  const src = style?.start ?? style?.main ?? style?.peak
  if (!src) return <span className={`${className ?? ''} is-empty`} aria-hidden="true" />
  return <img src={src} alt="" loading="lazy" decoding="async" className={className} />
}
