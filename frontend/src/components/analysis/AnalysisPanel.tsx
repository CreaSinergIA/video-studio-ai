import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Camera, ChevronDown, Clapperboard, ExternalLink, ScanFace, Trash, Wand } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Badge, EmptyState } from '@/components/ui/feedback'
import { keys } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatDuration, formatTimecode } from '@/lib/format'
import type { AnalysisFrame, AnalysisState, Scene } from '@/lib/types'

const TRANSITION: Record<string, string> = { start: 'Inicio', cut: 'Corte', dissolve: 'Disolución', fade: 'Fundido' }
const MOTION: Record<string, string> = { static: 'Estática', low: 'Movimiento bajo', medium: 'Movimiento medio', high: 'Movimiento alto' }
const BRIGHT: Record<string, string> = { dark: 'Oscura', normal: 'Luz normal', bright: 'Muy luminosa' }
const FACES: Record<string, string> = { unknown: 'Rostros: sin datos', none: 'Sin rostros', single: '1 rostro', multiple: 'Varios rostros' }
const REASON: Record<string, string> = { scene_start: 'Inicio', scene_mid: 'Centro', scene_end: 'Final', interval: 'Intervalo', on_demand: 'Captura' }

/** Fotograma con los rostros detectados dibujados (cajas y puntos de ojos y boca). */
export function FrameThumb({ frame, onClick, className }: { frame: AnalysisFrame; onClick?: () => void; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('group relative overflow-hidden rounded-lg border border-line bg-stage', className)}
      style={{ aspectRatio: `${frame.width} / ${frame.height}` }}
      title={`${REASON[frame.reason]} · ${formatTimecode(frame.t)}`}
    >
      <img src={frame.url} alt={`Fotograma en ${formatTimecode(frame.t)}`} loading="lazy" className="absolute inset-0 size-full object-cover" />
      {frame.faces?.map((f, i) => (
        <span key={i}>
          <span
            className="absolute rounded-sm border-2 border-[#3ddc97] shadow-[0_0_0_1px_rgba(0,0,0,0.4)]"
            style={{ left: `${f.box[0] * 100}%`, top: `${f.box[1] * 100}%`, width: `${f.box[2] * 100}%`, height: `${f.box[3] * 100}%` }}
          />
          {[f.right_eye, f.left_eye, f.mouth_right, f.mouth_left].map((p, k) => (
            <span key={k} className="absolute size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#3ddc97]" style={{ left: `${p[0] * 100}%`, top: `${p[1] * 100}%` }} />
          ))}
        </span>
      ))}
      <span className="absolute bottom-1 left-1 rounded bg-black/65 px-1 text-[10px] tabular text-white">{formatTimecode(frame.t)}</span>
    </button>
  )
}

function SceneRow({ scene, frames, onSeek }: { scene: Scene; frames: AnalysisFrame[]; onSeek: (t: number) => void }) {
  const [open, setOpen] = useState(false)
  const mid = frames.find((f) => f.reason === 'scene_mid') ?? frames[0]
  return (
    <li className="rounded-xl border border-line bg-surface-2/60">
      <div className="flex gap-3 p-2.5">
        {mid ? (
          <FrameThumb frame={mid} onClick={() => onSeek(scene.start)} className="w-[72px] shrink-0" />
        ) : (
          <div className="grid w-[72px] shrink-0 place-items-center rounded-lg bg-surface-3 text-fg-faint">
            <Clapperboard className="size-4" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <button type="button" onClick={() => onSeek(scene.start)} className="text-left text-[13px] font-semibold text-fg hover:text-accent">
            Escena {scene.index + 1}
            <span className="ml-1.5 font-normal tabular text-fg-faint">
              {formatTimecode(scene.start)} – {formatTimecode(scene.end)} · {formatDuration(scene.duration)}
            </span>
          </button>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <Badge className="h-5 text-[10.5px]" tone={scene.transition_in === 'cut' ? 'accent' : 'neutral'}>{TRANSITION[scene.transition_in]}</Badge>
            <Badge className="h-5 text-[10.5px]">{MOTION[scene.labels.motion]}</Badge>
            <Badge className="h-5 text-[10.5px]">{BRIGHT[scene.labels.brightness]}</Badge>
            <Badge className="h-5 text-[10.5px]" tone={scene.labels.faces === 'single' || scene.labels.faces === 'multiple' ? 'success' : 'neutral'}>
              {FACES[scene.labels.faces]}
            </Badge>
          </div>
          {frames.length > 0 && (
            <button type="button" onClick={() => setOpen((o) => !o)} className="mt-1.5 flex items-center gap-1 text-[11px] text-fg-faint hover:text-fg" aria-expanded={open}>
              <ChevronDown className={cn('size-3 transition', open && 'rotate-180')} />
              {frames.length} fotograma{frames.length === 1 ? '' : 's'}
            </button>
          )}
        </div>
      </div>
      {open && (
        <div className="grid grid-cols-3 gap-1.5 border-t border-line p-2.5">
          {frames.map((f) => (
            <FrameThumb key={f.id} frame={f} onClick={() => onSeek(f.t)} />
          ))}
        </div>
      )}
    </li>
  )
}

export function AnalysisPanel({
  projectId,
  state,
  currentTime,
  onSeek,
  onAnalyze,
  analyzing,
}: {
  projectId: string
  state: AnalysisState | undefined
  currentTime: number
  onSeek: (t: number) => void
  onAnalyze: () => void
  analyzing: boolean
}) {
  const qc = useQueryClient()
  const [capturing, setCapturing] = useState(false)
  const visual = state?.visual
  const voice = state?.transcript?.stats.voice
  const frames = state?.frames ?? []
  const captures = frames.filter((f) => f.reason === 'on_demand')

  const capture = async () => {
    setCapturing(true)
    try {
      await api.captureFrame(projectId, currentTime)
      await qc.invalidateQueries({ queryKey: keys.analysis(projectId) })
    } catch (err) {
      toast.error('No se pudo capturar el fotograma', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setCapturing(false)
    }
  }

  if (!visual) {
    return (
      <EmptyState
        icon={<Clapperboard className="size-5" />}
        title="Sin análisis visual"
        description="Detecta cortes, transiciones, intervalos estáticos y rostros, y extrae fotogramas representativos."
        action={
          <Button variant="primary" loading={analyzing} icon={<Wand className="size-4" />} onClick={onAnalyze}>
            Analizar video
          </Button>
        }
      />
    )
  }
  const cuts = visual.transitions.filter((t) => t.kind === 'cut').length
  const gradual = visual.transitions.length - cuts
  const withFaces = visual.scenes.filter((s) => s.labels.faces === 'single' || s.labels.faces === 'multiple').length
  const summary: [string, string][] = [
    ['Escenas', String(visual.scenes.length)],
    ['Cortes', String(cuts)],
    ['Transiciones', String(gradual)],
    ['Estáticos', String(visual.static_intervals.length)],
    ['Con rostros', visual.faces_enabled ? `${withFaces}/${visual.scenes.length}` : '—'],
    ['Voz', voice ? `${Math.round(voice.speech_ratio * 100)} %` : '—'],
  ]
  return (
    <div className="space-y-4 px-4 py-4">
      <div className="grid grid-cols-3 gap-2">
        {summary.map(([k, v]) => (
          <div key={k} className="rounded-xl border border-line bg-surface-2 px-3 py-2">
            <div className="text-[15px] font-semibold tabular text-fg">{v}</div>
            <div className="text-[11px] text-fg-faint">{k}</div>
          </div>
        ))}
      </div>
      <p className="text-[11px] leading-snug text-fg-faint">
        {visual.frames_analyzed.toLocaleString('es')} fotogramas recorridos · {visual.frames_extracted} extraídos. Rostros detectados con YuNet: indica presencia, no quién habla.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" loading={capturing} icon={<Camera className="size-3.5" />} onClick={capture}>
          Capturar fotograma actual
        </Button>
        <Button size="sm" variant="ghost" icon={<ExternalLink className="size-3.5" />} onClick={() => window.open(`/api/projects/${projectId}/bundle`)}>
          Datos para la Fase 3 (JSON)
        </Button>
      </div>
      {captures.length > 0 && (
        <section>
          <h3 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">
            <ScanFace className="size-3.5" /> Capturas
          </h3>
          <div className="grid grid-cols-3 gap-1.5">
            {captures.map((f) => (
              <div key={f.id} className="group relative">
                <FrameThumb frame={f} onClick={() => onSeek(f.t)} />
                <button
                  type="button"
                  aria-label="Eliminar captura"
                  onClick={() => void api.deleteFrame(f.id).then(() => qc.invalidateQueries({ queryKey: keys.analysis(projectId) }))}
                  className="absolute right-1 top-1 grid size-6 place-items-center rounded-md bg-black/60 text-white opacity-0 transition group-hover:opacity-100"
                >
                  <Trash className="size-3" />
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
      <section>
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">Escenas</h3>
        <ul className="space-y-1.5">
          {visual.scenes.map((sc) => (
            <SceneRow key={sc.index} scene={sc} frames={frames.filter((f) => f.scene_index === sc.index)} onSeek={onSeek} />
          ))}
        </ul>
      </section>
      {visual.static_intervals.length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">Intervalos estáticos</h3>
          <div className="flex flex-wrap gap-1.5">
            {visual.static_intervals.map(([a, b]) => (
              <button key={a} type="button" onClick={() => onSeek(a)} className="rounded-md border border-line bg-surface-2 px-2 py-1 text-xs tabular text-fg-muted hover:text-fg">
                {formatTimecode(a)} – {formatTimecode(b)}
              </button>
            ))}
          </div>
        </section>
      )}
      <Button size="sm" variant="ghost" loading={analyzing} icon={<Wand className="size-3.5" />} onClick={onAnalyze}>
        Volver a analizar
      </Button>
    </div>
  )
}
