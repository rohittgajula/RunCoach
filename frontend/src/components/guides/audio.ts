import { useCallback, useEffect, useRef, useState } from 'react'

type Ctor = typeof AudioContext

/** A fresh AudioContext — only ever from a tap (browsers block audio before a gesture). */
export function newAudio(): AudioContext | null {
  const C: Ctor | undefined = window.AudioContext ?? (window as unknown as { webkitAudioContext?: Ctor }).webkitAudioContext
  if (!C) return null
  try {
    return new C()
  } catch {
    return null
  }
}

/** A short click/beep at `when` (context time). */
export function beep(ctx: AudioContext, when = ctx.currentTime, freq = 1000, length = 0.04, volume = 0.35) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.value = freq
  gain.gain.setValueAtTime(volume, when)
  gain.gain.exponentialRampToValueAtTime(0.001, when + length)
  osc.connect(gain).connect(ctx.destination)
  osc.start(when)
  osc.stop(when + length + 0.01)
}

/** One context for a component's beeps; closed on unmount. */
export function useBeeper() {
  const ctx = useRef<AudioContext | null>(null)
  const ensure = useCallback(() => {
    if (!ctx.current || ctx.current.state === 'closed') ctx.current = newAudio()
    if (ctx.current?.state === 'suspended') ctx.current.resume().catch(() => {})
    return ctx.current
  }, [])
  const play = useCallback((freq = 880, length = 0.12) => {
    const c = ctx.current
    if (c && c.state !== 'closed') beep(c, c.currentTime, freq, length)
  }, [])
  useEffect(() => () => {
    ctx.current?.close().catch(() => {})
    ctx.current = null
  }, [])
  return { ensure, play }
}

/**
 * Cadence metronome: clicks scheduled ahead on the audio clock (steady even when the
 * main thread is busy). Stops on unmount — i.e. when the guide sheet closes.
 */
export function useMetronome(bpm: number) {
  const [running, setRunning] = useState(false)
  const ctx = useRef<AudioContext | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const next = useRef(0)
  const beat = useRef(0)
  const rate = useRef(bpm)

  useEffect(() => {
    rate.current = bpm
  }, [bpm])

  const stop = useCallback(() => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
    ctx.current?.close().catch(() => {})
    ctx.current = null
    setRunning(false)
  }, [])

  const start = useCallback(() => {
    stop()
    const c = newAudio()
    if (!c) return false
    ctx.current = c
    next.current = c.currentTime + 0.06
    beat.current = 0
    timer.current = setInterval(() => {
      while (next.current < c.currentTime + 0.12) {
        // Every 4th step a little higher, so the count is easy to follow.
        beep(c, next.current, beat.current % 4 === 0 ? 1320 : 990, 0.03, 0.3)
        beat.current += 1
        next.current += 60 / rate.current
      }
    }, 25)
    setRunning(true)
    return true
  }, [stop])

  useEffect(() => stop, [stop])

  // Hidden tab: stop rather than click into the void.
  useEffect(() => {
    const onHide = () => document.hidden && stop()
    document.addEventListener('visibilitychange', onHide)
    return () => document.removeEventListener('visibilitychange', onHide)
  }, [stop])

  return { running, start, stop }
}

export const mmss = (s: number) => {
  const v = Math.max(0, Math.ceil(s))
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`
}
