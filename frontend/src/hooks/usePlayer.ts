import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

export interface PlayerState {
  currentTime: number
  duration: number
  playing: boolean
  volume: number
  muted: boolean
}

export interface PlayerApi {
  videoRef: RefObject<HTMLVideoElement | null>
  state: PlayerState
  seek: (t: number) => void
  toggle: () => void
  step: (seconds: number) => void
  setVolume: (v: number) => void
  setMuted: (m: boolean) => void
  onMediaEvent: () => void
}

/** Estado del reproductor con actualización fluida del cabezal (requestAnimationFrame). */
export function usePlayer(initial: { volume: number; muted: boolean }): PlayerApi {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [state, setState] = useState<PlayerState>({
    currentTime: 0,
    duration: 0,
    playing: false,
    volume: initial.volume,
    muted: initial.muted,
  })

  const sync = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    setState((s) => {
      const next = {
        currentTime: v.currentTime,
        duration: Number.isFinite(v.duration) ? v.duration : s.duration,
        playing: !v.paused && !v.ended,
        volume: v.volume,
        muted: v.muted,
      }
      return next.currentTime === s.currentTime &&
        next.duration === s.duration &&
        next.playing === s.playing &&
        next.volume === s.volume &&
        next.muted === s.muted
        ? s
        : next
    })
  }, [])

  useEffect(() => {
    if (!state.playing) return
    let frame = 0
    const loop = () => {
      sync()
      frame = requestAnimationFrame(loop)
    }
    frame = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(frame)
  }, [state.playing, sync])

  const seek = useCallback(
    (t: number) => {
      const v = videoRef.current
      if (!v) return
      const max = Number.isFinite(v.duration) ? v.duration : t
      v.currentTime = Math.max(0, Math.min(max, t))
      sync()
    },
    [sync],
  )
  const toggle = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused || v.ended) void v.play().catch(() => undefined)
    else v.pause()
  }, [])
  const step = useCallback((seconds: number) => {
    const v = videoRef.current
    if (v) seek(v.currentTime + seconds)
  }, [seek])
  const setVolume = useCallback((value: number) => {
    const v = videoRef.current
    if (!v) return
    v.volume = value
    if (value > 0 && v.muted) v.muted = false
  }, [])
  const setMuted = useCallback((m: boolean) => {
    if (videoRef.current) videoRef.current.muted = m
  }, [])

  return { videoRef, state, seek, toggle, step, setVolume, setMuted, onMediaEvent: sync }
}
