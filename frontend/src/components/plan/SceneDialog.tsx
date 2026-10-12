import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, CircleAlert, Clapperboard, Download, History, Pause, Play, RotateCcw, Sparkles, Trash2, Volume2, Wand2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge, ProgressBar, Spinner } from '@/components/ui/feedback'
import { Segmented } from '@/components/ui/fields'
import { BudgetDeclined, useBudget } from '@/hooks/budget-context'
import { keys, useScene } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { TYPE_META, fmtT } from '@/lib/plan'
import type { SceneVersion } from '@/lib/types'

const EXAMPLES = [
  'Haz la animación más fluida',
  'Que los nodos se conecten progresivamente',
  'Utiliza menos texto',
  'Haz el título más grande',
  'Reduce el movimiento',
  'Cambia esta composición por un diagrama',
  'No coloques elementos sobre mi rostro',
  'Quiero una transición más elaborada',
]

const STATUS: Record<SceneVersion['status'], { label: string; tone: 'success' | 'accent' | 'neutral' | 'danger' }> = {
  applied: { label: 'En uso', tone: 'success' },
  candidate: { label: 'Propuesta', tone: 'accent' },
  archived: { label: 'Anterior', tone: 'neutral' },
  discarded: { label: 'Descartada', tone: 'danger' },
}
const SOURCE: Record<SceneVersion['source'], string> = {
  approved: 'Aprobada en el plan',
  claude: 'Modificada por Claude',
  restored: 'Recuperada',
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

/** Dos vistas previas reales de la misma ventana, reproducidas a la vez. */
function Compare({ left, right }: { left: SceneVersion; right: SceneVersion | null }) {
  const a = useRef<HTMLVideoElement>(null)
  const b = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [audio, setAudio] = useState<'left' | 'right'>('right')
  const both = () => [a.current, b.current].filter(Boolean) as HTMLVideoElement[]
  const toggle = () => {
    const vs = both()
    if (playing) vs.forEach((v) => v.pause())
    else {
      const t = vs[0]?.currentTime ?? 0
      vs.forEach((v) => {
        if (Math.abs(v.currentTime - t) > 0.05) v.currentTime = t
        void v.play()
      })
    }
    setPlaying(!playing)
  }
  const restart = () => {
    both().forEach((v) => {
      v.currentTime = 0
      void v.play()
    })
    setPlaying(true)
  }
  const pane = (v: SceneVersion | null, ref: React.RefObject<HTMLVideoElement | null>, side: 'left' | 'right', label: string) => (
    <figure className="min-w-0 flex-1">
      <figcaption className="mb-1 flex items-center gap-1.5 text-xs font-medium text-fg-muted">
        {label}
        {v && <span className="text-fg-faint">· v{v.number}</span>}
        {v && audio === side && <Volume2 className="size-3 text-accent" aria-label="Audio de este lado" />}
      </figcaption>
      {v?.preview ? (
        <video
          ref={ref}
          src={v.preview.url}
          muted={audio !== side}
          playsInline
          onEnded={() => setPlaying(false)}
          aria-label={`Vista previa ${label}`}
          className="max-h-[40vh] w-full rounded-lg bg-black object-contain"
        />
      ) : (
        <div className="grid aspect-[9/16] max-h-[40vh] w-full place-items-center rounded-lg bg-surface-3 px-4 text-center text-xs text-fg-faint">
          {v ? 'Sin vista previa todavía' : 'Elige una versión para comparar'}
        </div>
      )}
    </figure>
  )
  return (
    <div>
      <div className="flex gap-3">
        {pane(left, a, 'left', 'En uso')}
        {pane(right, b, 'right', right?.status === 'candidate' ? 'Propuesta' : 'Versión elegida')}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" icon={playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} onClick={toggle} disabled={!left.preview && !right?.preview}>
          {playing ? 'Pausar' : 'Reproducir ambas'}
        </Button>
        <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={restart} disabled={!left.preview && !right?.preview}>
          Desde el inicio
        </Button>
        <Segmented
          className="ml-auto"
          size="sm"
          label="Audio de"
          value={audio}
          onValueChange={setAudio}
          options={[
            { value: 'left', label: 'Audio: en uso' },
            { value: 'right', label: 'Audio: comparada' },
          ]}
        />
      </div>
      {left.preview && (
        <p className="mt-1 text-[11px] text-fg-faint">
          Tramo {fmtT(left.preview.window[0])}–{fmtT(left.preview.window[1])} compuesto con el mismo motor que la exportación (540p), con subtítulos, efectos y animaciones vecinas reales.
        </p>
      )}
    </div>
  )
}

export function SceneDialog({
  projectId,
  iid,
  onClose,
  onExport,
}: {
  projectId: string
  iid: string | null
  onClose: () => void
  onExport?: () => void
}) {
  const qc = useQueryClient()
  const budget = useBudget()
  const { data, isError, error } = useScene(projectId, iid)
  const [instruction, setInstruction] = useState('')
  const [pending, setPending] = useState(false)
  const [compareN, setCompareN] = useState<number | null>(null)
  const [confirmApply, setConfirmApply] = useState<SceneVersion | null>(null)
  const job = data?.job ?? null
  const busy = pending || Boolean(job)
  const versions = useMemo(() => data?.versions ?? [], [data])
  const inUse = versions.find((v) => v.in_use) ?? null
  // Por defecto se compara con la propuesta más reciente.
  const latestCandidate = versions.find((v) => v.status === 'candidate') ?? null
  const right = versions.find((v) => v.number === compareN) ?? latestCandidate
  const prevJob = useRef<string | null>(null)
  useEffect(() => {
    // Al terminar una tarea se refrescan animaciones y plan (pueden haber cambiado).
    if (prevJob.current && !job) {
      void qc.invalidateQueries({ queryKey: keys.animations(projectId) })
      void qc.invalidateQueries({ queryKey: keys.plan(projectId) })
    }
    prevJob.current = job?.id ?? null
  }, [job, projectId, qc])

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.scene(projectId, iid ?? '') })
    void qc.invalidateQueries({ queryKey: keys.jobs })
    void qc.invalidateQueries({ queryKey: keys.budget })
  }
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setPending(true)
    try {
      await fn()
      if (ok) toast.success(ok)
      refresh()
      return true
    } catch (err) {
      if (err instanceof BudgetDeclined) toast.info(err.message)
      else toast.error('No se pudo completar', { description: errorText(err) })
      return false
    } finally {
      setPending(false)
    }
  }
  const modify = () =>
    run(async () => {
      const text = instruction.trim()
      const r = await budget((c) => api.reviseScene(projectId, iid as string, { instruction: text, confirm_budget: c }))
      if (r.reused) toast.info(`Ya existía una propuesta con esa instrucción (versión ${r.version}): se reutiliza sin consultar a Claude.`)
      else setInstruction('')
      setCompareN(r.version ?? null)
    }, undefined)
  const preview = (v: SceneVersion) => run(() => api.previewSceneVersion(projectId, iid as string, v.number, inUse?.number), 'Preparando la vista previa')
  const apply = (v: SceneVersion) =>
    run(async () => {
      const r = await api.applySceneVersion(projectId, iid as string, v.number)
      toast.success(`Versión ${v.number} en uso (plan v${r.plan_version})`, {
        description:
          (r.draft_kept ? `Tu borrador del plan (v${r.draft_kept}) se conserva en el historial. ` : '') +
          'Se generan solo las animaciones que cambian; el resto sale de la caché.',
      })
      setConfirmApply(null)
      setCompareN(null)
    })
  const discard = (v: SceneVersion) => run(() => api.discardSceneVersion(projectId, iid as string, v.number), 'Propuesta descartada')

  if (!iid) return null
  const est = data?.budget
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      size="xl"
      icon={<Clapperboard className="size-5" />}
      title={data ? `Escena · ${TYPE_META[data.type].label}` : 'Escena'}
      description={
        data
          ? `${fmtT(data.start)}–${fmtT(data.end)} · plan aprobado v${data.plan_version} · versión en uso v${data.in_use}. Los cambios crean versiones nuevas; nada se sobrescribe.`
          : undefined
      }
    >
      {isError && <p className="text-sm text-danger">{errorText(error)}</p>}
      {data && inUse && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-4">
            <Compare left={inUse} right={right && right.id !== inUse.id ? right : null} />
            {!inUse.preview && (!right || right.id === inUse.id) && (
              <Button size="sm" variant="secondary" icon={<Play className="size-3.5" />} disabled={busy} onClick={() => void preview(inUse)}>
                Generar la vista previa de la versión en uso
              </Button>
            )}
            {right && right.id !== inUse.id && !right.preview && (
              <Button size="sm" variant="secondary" icon={<Sparkles className="size-3.5" />} disabled={busy} onClick={() => void preview(right)}>
                Generar vistas previas para comparar v{inUse.number} y v{right.number}
              </Button>
            )}
            {job ? (
              <div className="rounded-xl border border-line bg-surface-2 p-3" role="status" aria-live="polite">
                <div className="mb-1 flex items-center gap-2 text-xs text-fg">
                  <Spinner className="size-3" /> {job.stage ?? job.label}
                  <span className="ml-auto tabular text-fg-muted">{Math.round(job.progress * 100)} %</span>
                </div>
                <ProgressBar value={job.progress} label="Progreso" />
                <div className="mt-1.5 flex justify-end">
                  <Button size="sm" variant="ghost" className="h-7" onClick={() => void run(() => api.cancelJob(job.id), 'Cancelado')}>
                    Cancelar
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-line bg-surface-2 p-3">
                <label htmlFor="scene-instruction" className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-fg">
                  <Wand2 className="size-3.5" /> Modificar animación
                </label>
                <textarea
                  id="scene-instruction"
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  rows={2}
                  maxLength={1000}
                  placeholder="Describe el cambio, p. ej. «Haz el título más grande»"
                  className="w-full resize-none rounded-lg border border-line bg-surface-1 px-3 py-2 text-sm text-fg placeholder:text-fg-faint focus:border-accent focus:outline-none"
                />
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      type="button"
                      onClick={() => setInstruction(ex)}
                      className="rounded-full border border-line px-2 py-0.5 text-[11px] text-fg-muted transition hover:border-accent hover:text-fg"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
                <div className="mt-2.5 flex items-center gap-3">
                  <p className="min-w-0 flex-1 text-[11px] leading-snug text-fg-faint">
                    Claude cambia solo esta escena ({est?.estimate.expected ?? 1} solicitud; hasta {est?.estimate.maximum ?? 1} con reintentos). Usadas en 24 h: {est?.used_24h ?? 0} de {est?.limit_24h ?? '—'}. Se reutilizan la transcripción, los fotogramas y el plan aprobado.
                  </p>
                  <Button variant="primary" size="sm" icon={<Sparkles className="size-3.5" />} disabled={busy || instruction.trim().length < 3} onClick={() => void modify()}>
                    Modificar
                  </Button>
                </div>
              </div>
            )}
          </div>
          <aside aria-label="Versiones de la escena">
            <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-fg">
              <History className="size-3.5" /> Versiones ({versions.length})
            </h3>
            <ol className="space-y-2">
              {versions.map((v) => {
                const st = STATUS[v.status]
                const selected = right?.id === v.id
                return (
                  <li key={v.id} className={`rounded-lg border p-2.5 ${selected ? 'border-accent bg-accent-soft/40' : 'border-line bg-surface-1'}`}>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-mono text-xs font-semibold text-fg">v{v.number}</span>
                      <Badge tone={st.tone} className="h-5 text-[10.5px]">
                        {st.label}
                      </Badge>
                      <span className="text-[10.5px] text-fg-faint">{SOURCE[v.source]}</span>
                      {v.template && <span className="font-mono text-[10.5px] text-fg-faint">{v.template}</span>}
                    </div>
                    {v.instruction && <p className="mt-1 text-[12px] text-fg">«{v.instruction}»</p>}
                    {v.summary && <p className="mt-0.5 text-[11.5px] text-fg-muted">{v.summary}</p>}
                    {!v.in_use && v.impact.visual_change != null && (
                      <p className="mt-0.5 text-[11px] text-fg-faint">
                        Diferencia visible medida: {(v.impact.visual_change * 100).toFixed(1)} % de la región de la escena
                      </p>
                    )}
                    {v.diff.length > 0 && (
                      <details className="mt-1 text-[11px] text-fg-muted">
                        <summary className="cursor-pointer text-fg-faint">Qué cambia respecto a la versión en uso ({v.diff.length})</summary>
                        <ul className="mt-1 list-disc pl-4">
                          {v.diff.map((d) => (
                            <li key={d}>{d}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {!v.in_use && (v.impact.affected?.length ?? 0) > 0 && (
                      <p className="mt-1 flex gap-1 text-[11px] text-warning">
                        <CircleAlert className="mt-0.5 size-3 shrink-0" />
                        También se regenerará: {v.impact.affected!.map((a) => `${fmtT(a.start)}–${fmtT(a.end)} (${a.reasons.join('; ')})`).join(' · ')}
                      </p>
                    )}
                    {!v.in_use && v.status !== 'discarded' && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" disabled={selected} onClick={() => setCompareN(v.number)}>
                          Comparar
                        </Button>
                        <Button size="sm" variant="secondary" className="h-6 px-2 text-[11px]" icon={<Check className="size-3" />} disabled={busy} onClick={() => setConfirmApply(v)}>
                          {v.status === 'archived' ? 'Recuperar' : 'Usar esta versión'}
                        </Button>
                        {v.status === 'candidate' && (
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" icon={<Trash2 className="size-3" />} disabled={busy} onClick={() => void discard(v)}>
                            Descartar
                          </Button>
                        )}
                      </div>
                    )}
                    {v.status === 'discarded' && (
                      <Button size="sm" variant="ghost" className="mt-1 h-6 px-2 text-[11px]" disabled={busy} onClick={() => setConfirmApply(v)}>
                        Usar de todos modos
                      </Button>
                    )}
                  </li>
                )
              })}
            </ol>
            {onExport && (
              <Button className="mt-3 w-full" size="sm" variant="secondary" icon={<Download className="size-3.5" />} disabled={busy} onClick={onExport}>
                Exportar el video actualizado
              </Button>
            )}
          </aside>
        </div>
      )}
      <Dialog
        open={Boolean(confirmApply)}
        onOpenChange={(o) => !o && setConfirmApply(null)}
        size="sm"
        icon={<Check className="size-5" />}
        title={`¿Usar la versión ${confirmApply?.number}?`}
        description="Se crea una nueva versión aprobada del plan con solo esta escena cambiada. Las versiones anteriores se conservan y puedes volver a ellas."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmApply(null)}>
              Cancelar
            </Button>
            <Button variant="primary" loading={pending} onClick={() => confirmApply && void apply(confirmApply)}>
              Usar esta versión
            </Button>
          </>
        }
      >
        {confirmApply && (
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
            <li>Se genera la animación de esta escena a tamaño final (sin solicitudes a Claude).</li>
            {(confirmApply.impact.affected?.length ?? 0) > 0 ? (
              <li className="text-warning">
                Además, por dependencias: {confirmApply.impact.affected!.map((a) => `${fmtT(a.start)}–${fmtT(a.end)} (${a.reasons.join('; ')})`).join(' · ')}.
              </li>
            ) : (
              <li>Ninguna otra escena cambia: el resto se reutiliza de la caché.</li>
            )}
          </ul>
        )}
      </Dialog>
    </Dialog>
  )
}
