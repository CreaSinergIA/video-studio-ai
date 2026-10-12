import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AudioLines, Clapperboard, Film, Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDuration, formatTimecode } from '@/lib/format'
import { STATUS_META, TYPE_META, fmtT, isPassive } from '@/lib/plan'
import type { Asset, PlanIntervention, Scene } from '@/lib/types'

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    setWidth(el.getBoundingClientRect().width)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

/** Intervalo «redondo» entre marcas para que haya ~1 etiqueta cada 90 px. */
function tickStep(duration: number, width: number) {
  const target = (duration / Math.max(1, width)) * 90
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
  return steps.find((s) => s >= target) ?? 3600
}

const FILM_H = 52
const WAVE_H = 44

function Filmstrip({ strip, width, duration }: { strip: NonNullable<Asset['filmstrip']>; width: number; duration: number }) {
  const tileW = (FILM_H * strip.tile_width) / strip.tile_height
  const slots = Math.max(1, Math.ceil(width / tileW))
  const tiles = Array.from({ length: slots }, (_, i) => {
    const center = ((i + 0.5) * tileW * duration) / width
    const index = Math.min(strip.count - 1, Math.max(0, Math.floor(center / strip.interval)))
    return { i, index }
  })
  return (
    <div className="relative flex overflow-hidden rounded-md" style={{ height: FILM_H }}>
      {tiles.map(({ i, index }) => (
        <div
          key={i}
          className="h-full shrink-0 border-r border-black/40"
          style={{
            width: tileW,
            backgroundImage: `url(${strip.url})`,
            backgroundSize: `${strip.count * 100}% 100%`,
            backgroundPosition: `${strip.count > 1 ? (index / (strip.count - 1)) * 100 : 0}% 0`,
          }}
        />
      ))}
    </div>
  )
}

function Waveform({ url, width }: { url: string; width: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { data, isError } = useQuery({ queryKey: ['waveform', url], queryFn: () => api.waveform(url), staleTime: Infinity })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data || width <= 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(WAVE_H * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, WAVE_H)
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#9d8cff'
    const peaks = data.peaks
    const norm = data.max_peak > 0 ? 1 / data.max_peak : 1
    const bar = 2
    const gap = 1
    const columns = Math.floor(width / (bar + gap))
    const mid = WAVE_H / 2
    ctx.fillStyle = accent
    for (let c = 0; c < columns; c++) {
      const start = Math.floor((c / columns) * peaks.length)
      const end = Math.max(start + 1, Math.floor(((c + 1) / columns) * peaks.length))
      let max = 0
      for (let i = start; i < end && i < peaks.length; i++) max = Math.max(max, peaks[i])
      const h = Math.max(1, Math.sqrt(max * norm) * (WAVE_H - 6))
      ctx.globalAlpha = 0.85
      ctx.fillRect(c * (bar + gap), mid - h / 2, bar, h)
    }
  }, [data, width])

  if (isError) return <div className="grid h-full place-items-center text-xs text-fg-faint">No se pudo cargar la forma de onda</div>
  return <canvas ref={canvasRef} style={{ width, height: WAVE_H }} aria-label="Forma de onda del audio" role="img" />
}

const SCENE_H = 16
const PLAN_H = 22

/** Carril de propuestas de edición: tipo (color), estado (relleno) y relación con el original. */
function PlanLane({
  items,
  width,
  duration,
  selected,
  onSelect,
  animation,
}: {
  items: PlanIntervention[]
  width: number
  duration: number
  selected: string | null
  onSelect: (item: PlanIntervention) => void
  animation?: Record<string, string>
}) {
  return (
    <div className="relative overflow-hidden rounded-md bg-surface-2" style={{ height: PLAN_H }} aria-label="Propuestas de edición">
      {items.map((i) => {
        const meta = TYPE_META[i.type]
        const left = (i.start / duration) * width
        const w = Math.max(3, ((i.end - i.start) / duration) * width)
        const passive = isPassive(i)
        const accepted = i.status === 'accepted'
        const rejected = i.status === 'rejected'
        return (
          <button
            key={i.id}
            type="button"
            data-plan-id={i.id}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation()
              onSelect(i)
            }}
            title={`${meta.label} · ${fmtT(i.start)}–${fmtT(i.end)} · ${STATUS_META[i.status].label}${i.stale ? ' · obsoleta' : ''}\n${i.goal}`}
            aria-label={`${meta.label} de ${fmtT(i.start)} a ${fmtT(i.end)}, ${STATUS_META[i.status].label}`}
            className={`absolute top-0.5 bottom-0.5 overflow-hidden rounded-[4px] border text-left text-[9.5px] font-semibold leading-[18px] text-white/95 transition ${
              selected === i.id ? 'z-10 ring-2 ring-white' : ''
            } ${i.stale ? 'border-dashed' : ''} ${rejected ? 'opacity-30' : ''} ${i.status === 'needs_changes' ? 'outline outline-1 outline-warning' : ''}`}
            style={{
              left,
              width: w,
              borderColor: meta.color,
              background: passive
                ? 'transparent'
                : accepted
                  ? `${meta.color}cc`
                  : `repeating-linear-gradient(135deg, ${meta.color}55 0 5px, ${meta.color}33 5px 10px)`,
              textDecoration: rejected ? 'line-through' : undefined,
            }}
          >
            {w > 46 && <span className="px-1">{meta.short}</span>}
            {animation?.[i.id] && animation[i.id] !== 'kept' && (
              <span
                className={`absolute right-0.5 top-0.5 size-1.5 rounded-full ${
                  animation[i.id] === 'ready' ? 'bg-success' : animation[i.id] === 'failed' ? 'bg-danger' : animation[i.id] === 'rendering' ? 'animate-pulse bg-white' : 'bg-white/40'
                }`}
                title={`Animación: ${animation[i.id] === 'ready' ? 'disponible' : animation[i.id] === 'failed' ? 'error' : animation[i.id] === 'rendering' ? 'generando' : 'pendiente'}`}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}

function ScenesLane({ scenes, width, duration }: { scenes: Scene[]; width: number; duration: number }) {
  return (
    <div className="relative overflow-hidden rounded-md bg-surface-2" style={{ height: SCENE_H }}>
      {scenes.map((sc) => (
        <div
          key={sc.index}
          title={`Escena ${sc.index + 1} · ${formatTimecode(sc.start)} – ${formatTimecode(sc.end)}`}
          className={`absolute inset-y-0 border-l ${sc.index % 2 ? 'bg-accent/25' : 'bg-accent/45'} ${sc.transition_in === 'cut' ? 'border-white/80' : 'border-white/25'}`}
          style={{ left: (sc.start / duration) * width, width: Math.max(1, ((sc.end - sc.start) / duration) * width) }}
        >
          {((sc.end - sc.start) / duration) * width > 22 && (
            <span className="absolute left-1 top-0 text-[9.5px] font-semibold leading-4 text-white/90">{sc.index + 1}</span>
          )}
        </div>
      ))}
    </div>
  )
}

export function Timeline({
  asset,
  currentTime,
  onSeek,
  scenes,
  speech,
  plan,
  selectedPlan = null,
  onSelectPlan,
  animation,
}: {
  asset: Asset
  currentTime: number
  onSeek: (t: number) => void
  scenes?: Scene[]
  speech?: [number, number][]
  plan?: PlanIntervention[]
  selectedPlan?: string | null
  onSelectPlan?: (item: PlanIntervention) => void
  animation?: Record<string, string>
}) {
  const [trackRef, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const duration = asset.duration
  const step = tickStep(duration, width)
  const ticks = useMemo(() => {
    const out: number[] = []
    for (let t = 0; t <= duration + 1e-6; t += step) out.push(t)
    return out
  }, [duration, step])
  const toX = (t: number) => (duration > 0 ? (t / duration) * width : 0)
  const timeAt = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect) return 0
    return Math.max(0, Math.min(duration, ((clientX - rect.left) / rect.width) * duration))
  }

  return (
    <div className="border-t border-line bg-surface-1 px-4 pb-4 pt-2.5">
      <div className="mb-2 flex items-center justify-between text-[11px] font-medium uppercase tracking-wide text-fg-faint">
        <span>Línea de tiempo · original</span>
        <span className="normal-case tracking-normal tabular">
          {formatTimecode(currentTime)} / {formatDuration(duration)}
        </span>
      </div>
      <div className="flex gap-3">
        <div className="flex w-7 shrink-0 flex-col items-center gap-0 pt-[22px] text-fg-faint">
          {plan && plan.length > 0 && (
            <div className="mb-1.5 grid place-items-center" style={{ height: PLAN_H }} title="Plan de edición (propuestas de Claude)">
              <Sparkles className="size-3.5" />
            </div>
          )}
          {scenes && scenes.length > 0 && (
            <div className="mb-1.5 grid place-items-center" style={{ height: SCENE_H }} title="Escenas">
              <Clapperboard className="size-3.5" />
            </div>
          )}
          <div className="grid place-items-center" style={{ height: FILM_H }} title="Video">
            <Film className="size-4" />
          </div>
          {asset.has_audio && (
            <div className="mt-1.5 grid place-items-center" style={{ height: WAVE_H }} title="Audio">
              <AudioLines className="size-4" />
            </div>
          )}
        </div>
        <div
          ref={trackRef}
          className="relative min-w-0 flex-1 cursor-pointer select-none touch-none"
          role="slider"
          tabIndex={0}
          aria-label="Línea de tiempo"
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(currentTime)}
          aria-valuetext={formatTimecode(currentTime)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') onSeek(currentTime - (e.shiftKey ? 1 : 5))
            if (e.key === 'ArrowRight') onSeek(currentTime + (e.shiftKey ? 1 : 5))
          }}
          onPointerMove={(e) => setHover(timeAt(e.clientX))}
          onPointerLeave={() => setHover(null)}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId)
            onSeek(timeAt(e.clientX))
            const move = (ev: PointerEvent) => onSeek(timeAt(ev.clientX))
            const up = () => {
              window.removeEventListener('pointermove', move)
              window.removeEventListener('pointerup', up)
            }
            window.addEventListener('pointermove', move)
            window.addEventListener('pointerup', up)
          }}
        >
          {/* Regla */}
          <div className="relative h-[18px] border-b border-line">
            {width > 0 &&
              ticks.map((t) => (
                <div key={t} className="absolute top-0 h-full" style={{ left: toX(t) }}>
                  <div className="h-1.5 w-px bg-line-strong" />
                  {toX(t) < width - 30 && (
                    <span className="absolute left-1 top-0.5 text-[10px] tabular text-fg-faint">{formatDuration(t)}</span>
                  )}
                </div>
              ))}
          </div>
          <div className="mt-1 space-y-1.5">
            {plan && plan.length > 0 && width > 0 && (
              <PlanLane items={plan} width={width} duration={duration} selected={selectedPlan} onSelect={(i) => onSelectPlan?.(i)} animation={animation} />
            )}
            {scenes && scenes.length > 0 && width > 0 && <ScenesLane scenes={scenes} width={width} duration={duration} />}
            {asset.filmstrip ? (
              width > 0 && <Filmstrip strip={asset.filmstrip} width={width} duration={duration} />
            ) : (
              <div className="skeleton rounded-md" style={{ height: FILM_H }} />
            )}
            {asset.has_audio && (
              <div className="relative overflow-hidden rounded-md bg-surface-2" style={{ height: WAVE_H }}>
                {speech?.map(([a, b]) => (
                  <div
                    key={a}
                    className="absolute inset-y-0 bg-success/10"
                    style={{ left: (a / duration) * width, width: Math.max(1, ((b - a) / duration) * width) }}
                    title={`Voz · ${formatTimecode(a)} – ${formatTimecode(b)}`}
                  />
                ))}
                {asset.waveform_url ? (
                  width > 0 && <Waveform url={asset.waveform_url} width={width} />
                ) : (
                  <div className="skeleton h-full" />
                )}
              </div>
            )}
          </div>
          {hover !== null && (
            <div className="pointer-events-none absolute bottom-0 top-0 w-px bg-white/30" style={{ left: toX(hover) }}>
              <span className="absolute -top-0.5 left-1.5 rounded bg-surface-4 px-1.5 py-0.5 text-[10px] tabular text-fg shadow">
                {formatTimecode(hover)}
              </span>
            </div>
          )}
          <div
            className="pointer-events-none absolute -bottom-1 top-0 w-0.5 -translate-x-1/2 bg-accent shadow-[0_0_12px_var(--accent)]"
            style={{ left: toX(currentTime) }}
          >
            <div className="absolute -left-[5px] top-0 size-3 rotate-45 rounded-[2px] bg-accent" />
          </div>
        </div>
      </div>
    </div>
  )
}
