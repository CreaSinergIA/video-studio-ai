import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { PlayerApi } from '@/hooks/usePlayer'
import {
  Frame,
  Captions,
  CircleAlert,
  Maximize,
  Minimize,
  Pause,
  Play,
  Repeat,
  SkipBack,
  SkipForward,
  Volume1,
  Volume2,
  VolumeX,
} from 'lucide-react'
import { Slider } from '@/components/ui/fields'
import { Kbd, Tooltip } from '@/components/ui/feedback'
import { cn } from '@/lib/cn'
import { formatTimecode } from '@/lib/format'

const DECODE_MESSAGE =
  'Este navegador no puede decodificar la imagen de este video. Crea un proxy de reproducción H.264; el original se conserva intacto.'

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return Boolean(el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.getAttribute('role') === 'slider'))
}

export function VideoPlayer({
  player,
  src,
  poster,
  width,
  height,
  fps,
  loop,
  autoPlay,
  initialPosition,
  overlay,
  overlayEnabled,
  onToggleOverlay,
  overlayLabel = 'muestra de estilo de subtítulos',
  guides,
  guidesEnabled = false,
  onToggleGuides,
  onLoopChange,
  onError,
  decodeAction,
}: {
  player: PlayerApi
  src: string
  poster?: string | null
  width: number
  height: number
  fps: number
  loop: boolean
  autoPlay: boolean
  initialPosition: number
  overlay?: ReactNode
  overlayEnabled: boolean
  onToggleOverlay: () => void
  overlayLabel?: string
  /** Guías de zonas seguras (solo en el panel; nunca se exportan). */
  guides?: ReactNode
  guidesEnabled?: boolean
  onToggleGuides?: () => void
  onLoopChange: (v: boolean) => void
  onError: (kind: 'decode' | 'network') => void
  /** Acción ofrecida cuando el navegador no puede decodificar el video (p. ej. crear proxy). */
  decodeAction?: ReactNode
}) {
  const { videoRef, state, toggle, step, seek, setVolume, setMuted, onMediaEvent } = player
  const containerRef = useRef<HTMLDivElement>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [error, setError] = useState<{ kind: 'decode' | 'network'; message: string } | null>(null)
  const [idle, setIdle] = useState(false)
  const restored = useRef<string | null>(null)

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === containerRef.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const [errorFor, setErrorFor] = useState(src)
  if (errorFor !== src) {
    setErrorFor(src)
    setError(null)
  }

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void containerRef.current?.requestFullscreen().catch(() => undefined)
  }, [])

  // Atajos de teclado del editor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return
      const frame = 1 / (fps || 30)
      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault()
          toggle()
          break
        case 'ArrowLeft':
          e.preventDefault()
          step(e.shiftKey ? -1 : -5)
          break
        case 'ArrowRight':
          e.preventDefault()
          step(e.shiftKey ? 1 : 5)
          break
        case ',':
          step(-frame)
          break
        case '.':
          step(frame)
          break
        case 'Home':
          seek(0)
          break
        case 'm':
          setMuted(!state.muted)
          break
        case 'f':
          toggleFullscreen()
          break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fps, seek, setMuted, state.muted, step, toggle, toggleFullscreen])

  // Ocultar controles tras inactividad durante la reproducción.
  useEffect(() => {
    if (!state.playing || idle) return
    const id = setTimeout(() => setIdle(true), 2200)
    return () => clearTimeout(id)
  }, [state.playing, idle])

  const VolumeIcon = state.muted || state.volume === 0 ? VolumeX : state.volume < 0.5 ? Volume1 : Volume2
  const progress = state.duration ? state.currentTime / state.duration : 0

  return (
    <div
      ref={containerRef}
      className={cn('relative flex h-full w-full items-center justify-center', fullscreen && 'bg-black')}
      style={{ containerType: 'size' }}
      onMouseMove={() => setIdle(false)}
    >
      <div
        className="@container relative overflow-hidden rounded-xl bg-black shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)] ring-1 ring-white/5"
        style={{
          aspectRatio: `${width} / ${height}`,
          width: `min(100cqw, calc(100cqh * ${width / height}))`,
        }}
      >
        <video
          ref={videoRef}
          src={src}
          poster={poster ?? undefined}
          preload="auto"
          playsInline
          loop={loop}
          autoPlay={autoPlay}
          className="size-full cursor-pointer bg-black object-contain"
          onClick={toggle}
          onDoubleClick={toggleFullscreen}
          onLoadedMetadata={(e) => {
            const v = e.currentTarget
            v.volume = state.volume
            v.muted = state.muted
            if (restored.current !== src && initialPosition > 0 && initialPosition < v.duration - 0.5) {
              v.currentTime = initialPosition
            }
            restored.current = src
            onMediaEvent()
          }}
          onLoadedData={(e) => {
            // Algunos navegadores cargan el audio pero no pueden decodificar la imagen (0×0).
            const v = e.currentTarget
            if (v.videoWidth === 0 && v.videoHeight === 0) {
              v.pause()
              setError({ kind: 'decode', message: DECODE_MESSAGE })
              onError('decode')
            }
          }}
          onPlay={onMediaEvent}
          onPause={onMediaEvent}
          onEnded={onMediaEvent}
          onSeeked={onMediaEvent}
          onTimeUpdate={onMediaEvent}
          onVolumeChange={onMediaEvent}
          onDurationChange={onMediaEvent}
          onError={(e) => {
            const kind = e.currentTarget.error?.code === 4 ? 'decode' : 'network'
            setError({
              kind,
              message:
                kind === 'decode'
                  ? DECODE_MESSAGE
                  : 'No se pudo cargar el video. Comprueba que el almacenamiento esté conectado.',
            })
            onError(kind)
          }}
        />
        {overlayEnabled && overlay}
        {guidesEnabled && guides}
        {error && (
          <div className="absolute inset-0 grid place-items-center bg-black/80 p-6 text-center">
            <div className="max-w-sm">
              <CircleAlert className="mx-auto mb-3 size-7 text-warning" />
              <p className="text-sm text-white/90">{error.message}</p>
              {error.kind === 'decode' && decodeAction && <div className="mt-4">{decodeAction}</div>}
            </div>
          </div>
        )}
        {!state.playing && !error && (
          <button
            type="button"
            onClick={toggle}
            className="absolute left-1/2 top-1/2 grid size-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-black/45 text-white ring-1 ring-white/20 backdrop-blur-md transition hover:scale-105 hover:bg-black/60"
            aria-label="Reproducir"
          >
            <Play className="ml-1 size-6 fill-current" />
          </button>
        )}
        <div
          className={cn(
            'absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-3 pb-2.5 pt-10 transition-opacity duration-300',
            idle && state.playing ? 'pointer-events-none opacity-0' : 'opacity-100',
          )}
        >
          <div
            className="group/scrub relative mb-2 h-3 cursor-pointer"
            onPointerDown={(e) => {
              const rect = e.currentTarget.getBoundingClientRect()
              const at = (x: number) => ((x - rect.left) / rect.width) * state.duration
              seek(at(e.clientX))
              e.currentTarget.setPointerCapture(e.pointerId)
              const move = (ev: PointerEvent) => seek(at(ev.clientX))
              const up = () => {
                window.removeEventListener('pointermove', move)
                window.removeEventListener('pointerup', up)
              }
              window.addEventListener('pointermove', move)
              window.addEventListener('pointerup', up)
            }}
            role="slider"
            aria-label="Posición de reproducción"
            aria-valuemin={0}
            aria-valuemax={Math.round(state.duration)}
            aria-valuenow={Math.round(state.currentTime)}
            aria-valuetext={formatTimecode(state.currentTime)}
            tabIndex={-1}
          >
            <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/20 transition-all group-hover/scrub:h-1.5">
              <div className="h-full rounded-full bg-white" style={{ width: `${progress * 100}%` }} />
            </div>
            <div
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white opacity-0 shadow transition group-hover/scrub:opacity-100"
              style={{ left: `${progress * 100}%` }}
            />
          </div>
          <div className="flex items-center gap-1 text-white">
            <ControlButton label={state.playing ? 'Pausa' : 'Reproducir'} shortcut="Espacio" onClick={toggle}>
              {state.playing ? <Pause className="size-[18px] fill-current" /> : <Play className="size-[18px] fill-current" />}
            </ControlButton>
            <div className="hidden items-center gap-1 @[34rem]:flex">
              <ControlButton label="Retroceder 5 s" shortcut="←" onClick={() => step(-5)}>
                <SkipBack className="size-4" />
              </ControlButton>
              <ControlButton label="Avanzar 5 s" shortcut="→" onClick={() => step(5)}>
                <SkipForward className="size-4" />
              </ControlButton>
            </div>
            <div className="group/vol flex items-center">
              <ControlButton label={state.muted ? 'Activar sonido' : 'Silenciar'} shortcut="M" onClick={() => setMuted(!state.muted)}>
                <VolumeIcon className="size-[18px]" />
              </ControlButton>
              <div className="w-0 overflow-hidden transition-all duration-200 group-focus-within/vol:w-28 group-hover/vol:w-28">
                <Slider
                  label="Volumen"
                  value={Math.round((state.muted ? 0 : state.volume) * 100)}
                  onValueChange={(v) => setVolume(v / 100)}
                  className="w-24 pl-1 [&>span]:hidden"
                />
              </div>
            </div>
            <span className="ml-1.5 whitespace-nowrap text-[11.5px] font-medium tabular text-white/90">
              {formatTimecode(state.currentTime)}
              <span className="text-white/45"> / {formatTimecode(state.duration)}</span>
            </span>
            <div className="ml-auto flex items-center gap-1">
              <ControlButton label={overlayEnabled ? `Ocultar ${overlayLabel}` : `Mostrar ${overlayLabel}`} onClick={onToggleOverlay} active={overlayEnabled}>
                <Captions className="size-[18px]" />
              </ControlButton>
              {onToggleGuides && (
                <ControlButton label={guidesEnabled ? 'Ocultar zonas seguras' : 'Mostrar zonas seguras'} onClick={onToggleGuides} active={guidesEnabled}>
                  <Frame className="size-4" />
                </ControlButton>
              )}
              <ControlButton label={loop ? 'Desactivar bucle' : 'Reproducir en bucle'} onClick={() => onLoopChange(!loop)} active={loop}>
                <Repeat className="size-4" />
              </ControlButton>
              <ControlButton label={fullscreen ? 'Salir de pantalla completa' : 'Pantalla completa'} shortcut="F" onClick={toggleFullscreen}>
                {fullscreen ? <Minimize className="size-4" /> : <Maximize className="size-4" />}
              </ControlButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ControlButton({
  label,
  shortcut,
  onClick,
  children,
  active,
}: {
  label: string
  shortcut?: string
  onClick: () => void
  children: ReactNode
  active?: boolean
}) {
  return (
    <Tooltip
      content={
        <span className="flex items-center gap-2">
          {label} {shortcut && <Kbd>{shortcut}</Kbd>}
        </span>
      }
    >
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        aria-pressed={active}
        className={cn(
          'grid size-8 place-items-center rounded-lg transition hover:bg-white/15',
          active ? 'text-[var(--accent-strong)]' : 'text-white',
        )}
      >
        {children}
      </button>
    </Tooltip>
  )
}
