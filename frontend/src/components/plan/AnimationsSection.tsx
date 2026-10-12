import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { CircleAlert, Clapperboard, Eye, Film, RefreshCw, Sparkles, Wand2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge, ProgressBar, Spinner } from '@/components/ui/feedback'
import { Segmented, Switch } from '@/components/ui/fields'
import { BudgetDeclined, useBudget } from '@/hooks/budget-context'
import { keys, useAnimationLayout, useAnimations, useProject, useSafeZones } from '@/hooks/queries'
import { SafeZoneGuides } from '@/components/editor/SafeZoneGuides'
import { ApiError, api } from '@/lib/api'
import { TYPE_META, fmtT } from '@/lib/plan'
import type { AnimationItem, AnimationLayout, AnimationStatus, Asset, SafeZoneProfile } from '@/lib/types'

const ANIM_STATUS: Record<AnimationStatus, { label: string; tone: 'neutral' | 'accent' | 'success' | 'danger' | 'warning' }> = {
  pending: { label: 'Pendiente de generación', tone: 'neutral' },
  rendering: { label: 'Generando', tone: 'accent' },
  ready: { label: 'Disponible', tone: 'success' },
  failed: { label: 'Error', tone: 'danger' },
  kept: { label: 'Se conserva el original', tone: 'neutral' },
}

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

/** Vista previa real (tramo compuesto con el mismo motor que la exportación) y comparación. */
function PreviewDialog({
  item,
  asset,
  onClose,
  profile,
  layout,
}: {
  item: AnimationItem | null
  asset: Asset
  onClose: () => void
  profile: SafeZoneProfile | null
  layout: AnimationLayout | null
}) {
  const [mode, setMode] = useState<'edited' | 'original'>('edited')
  const [guides, setGuides] = useState(false)
  const [t, setT] = useState(0)
  const ref = useRef<HTMLVideoElement>(null)
  const win0 = item?.preview?.window[0] ?? 0
  const win1 = item?.preview?.window[1] ?? 0
  useEffect(() => {
    const v = ref.current
    if (!v || mode !== 'original') return
    const stop = () => {
      if (v.currentTime >= win1) v.pause()
    }
    v.addEventListener('timeupdate', stop)
    return () => v.removeEventListener('timeupdate', stop)
  }, [mode, win1])
  const win = [win0, win1]
  if (!item?.preview) return null
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      title="Vista previa de la animación"
      icon={<Film className="size-5" />}
      description={`${TYPE_META[item.type].label} · ${fmtT(item.start)}–${fmtT(item.end)} · plantilla ${item.template ?? '—'} · dirección ${item.direction ?? '—'}. Tramo ±1 s compuesto con el mismo motor que la exportación (540p); no es el render final a tamaño completo.`}
    >
      <div className="mb-3 flex items-center gap-3">
        <Segmented
          label="Comparar"
          size="sm"
          value={mode}
          onValueChange={setMode}
          options={[
            { value: 'edited', label: 'Editado' },
            { value: 'original', label: 'Original' },
          ]}
        />
        <span className="text-xs text-fg-faint">
          Ventana {fmtT(win[0])}–{fmtT(win[1])}
        </span>
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-fg-muted">
          <Switch label="Zonas seguras" checked={guides} onCheckedChange={setGuides} />
          Zonas seguras ({profile?.name ?? '—'})
        </label>
      </div>
      <div className="relative mx-auto w-fit">
      <video
        key={mode}
        ref={ref}
        src={mode === 'edited' ? item.preview.url : (asset.stream_url ?? undefined)}
        controls
        autoPlay
        playsInline
        aria-label={mode === 'edited' ? 'Vista previa editada' : 'Tramo original'}
        className="mx-auto max-h-[62vh] rounded-lg bg-black"
        onTimeUpdate={(e) => setT(mode === 'original' ? e.currentTarget.currentTime : win[0] + e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          if (mode === 'original') e.currentTarget.currentTime = win[0]
        }}
      />
      {guides && (
        <SafeZoneGuides
          profile={profile}
          layout={layout ? { ...layout, items: layout.items.filter((i) => i.intervention_id === item.intervention_id) } : null}
          time={t}
          vertical={asset.display_height > asset.display_width * 1.1}
        />
      )}
      </div>
      {item.notes.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-xs text-fg-muted">
          {item.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

export function AnimationsSection({
  projectId,
  asset,
  approvedVersion,
  onSeek,
  onOpenScene,
}: {
  projectId: string
  asset: Asset
  approvedVersion: number
  onSeek: (t: number) => void
  onOpenScene?: (iid: string) => void
}) {
  const qc = useQueryClient()
  const budget = useBudget()
  const { data } = useAnimations(projectId)
  const platform = useProject(projectId).data?.config.delivery?.platform ?? 'universal'
  const profile = useSafeZones().data?.find((p) => p.id === platform) ?? null
  const layout = useAnimationLayout(projectId, platform, true)
  const [useClaude, setUseClaude] = useState(true)
  const [pending, setPending] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const job = data?.job ?? null
  const busy = pending || Boolean(job)
  const items = data?.items ?? []
  const s = data?.summary ?? {}
  const animated = items.filter((i) => i.status !== 'kept').length

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setPending(true)
    try {
      await fn()
      toast.success(ok)
      qc.invalidateQueries({ queryKey: keys.animations(projectId) })
      qc.invalidateQueries({ queryKey: keys.jobs })
    } catch (err) {
      if (err instanceof BudgetDeclined) toast.info(err.message)
      else toast.error('No se pudo iniciar', { description: errorText(err) })
    } finally {
      setPending(false)
    }
  }
  // Al terminar una vista previa recién pedida, se abre sola (derivado, sin efectos).
  const [waitingPreview, setWaitingPreview] = useState<string | null>(null)
  const ready = waitingPreview && !job ? items.find((i) => i.intervention_id === waitingPreview && i.preview) : undefined
  const shownId = open ?? ready?.intervention_id ?? null
  const opened = items.find((i) => i.intervention_id === shownId) ?? null

  return (
    <section className="rounded-xl border border-line bg-surface-2 p-3" aria-label="Animaciones del plan aprobado">
      <div className="mb-2 flex items-center gap-2">
        <Clapperboard className="size-4 text-fg-muted" />
        <h3 className="text-[13px] font-semibold text-fg">Animaciones · plan v{approvedVersion}</h3>
        {animated > 0 && (
          <span className="ml-auto text-[11px] text-fg-faint">
            {s.ready ?? 0}/{animated} disponibles{s.failed ? ` · ${s.failed} con error` : ''}
          </span>
        )}
      </div>
      {!data?.engine_ready && (
        <p className="mb-2 rounded-lg bg-warning/10 px-2.5 py-2 text-xs text-warning">
          El motor de animaciones no está listo. <Link to="/settings#engine" className="underline">Ajustes → Motor de animaciones</Link>.
        </p>
      )}
      {job ? (
        <div className="mb-2" role="status" aria-live="polite">
          <div className="mb-1 flex items-center gap-2 text-xs text-fg">
            <Spinner className="size-3" /> {job.stage ?? job.label}
            <span className="ml-auto tabular text-fg-muted">{Math.round(job.progress * 100)} %</span>
          </div>
          <ProgressBar value={job.progress} label="Progreso de las animaciones" />
          <div className="mt-1.5 flex justify-end">
            <Button size="sm" variant="ghost" className="h-7" onClick={() => void run(() => api.cancelJob(job.id), 'Cancelado')}>
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <div className="mb-2 space-y-2">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-muted">
            <Switch label="Dirección de Claude" checked={useClaude} onCheckedChange={setUseClaude} />
            Claude dirige cada animación (1–2 solicitudes; si no, compilador determinista)
          </label>
          <Button
            className="w-full"
            variant="primary"
            icon={<Sparkles className="size-4" />}
            disabled={busy || !data?.engine_ready || animated === 0}
            onClick={() => void run(() => budget((c) => api.prepareAnimations(projectId, { use_claude: useClaude, confirm_budget: c })), 'Generando animaciones')}
          >
            {(s.ready ?? 0) === 0 ? 'Generar animaciones' : (s.ready ?? 0) < animated ? 'Generar las que faltan' : 'Comprobar y actualizar (usa la caché)'}
          </Button>
        </div>
      )}
      {layout.data?.warnings.map((w) => (
        <p key={w.code} className="mb-2 flex gap-1.5 rounded-lg bg-warning/10 px-2.5 py-2 text-xs text-warning">
          <CircleAlert className="mt-0.5 size-3.5 shrink-0" /> {w.message}
        </p>
      ))}
      <ol className="space-y-1.5">
        {items.map((it) => {
          const st = ANIM_STATUS[it.status]
          return (
            <li key={it.intervention_id} className="rounded-lg border border-line bg-surface-1 p-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <button type="button" className="font-mono text-[11px] text-fg hover:text-accent" onClick={() => onSeek(it.start)}>
                  {fmtT(it.start)}–{fmtT(it.end)}
                </button>
                <span className="text-[11px] font-medium" style={{ color: TYPE_META[it.type].color }}>
                  {TYPE_META[it.type].short}
                </span>
                <Badge tone={st.tone} className="h-5 text-[10.5px]" icon={it.status === 'rendering' ? <Spinner className="size-2.5" /> : undefined}>
                  {st.label}
                </Badge>
                {it.template && <span className="font-mono text-[10.5px] text-fg-faint">{it.template}</span>}
                {it.direction && <span className="text-[10.5px] text-fg-faint">· {it.direction}</span>}
                {it.reused && <span className="text-[10.5px] text-fg-faint">· caché</span>}
                <div className="ml-auto flex gap-1">
                  {onOpenScene && it.status !== 'kept' && (
                    <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" icon={<Wand2 className="size-3" />} onClick={() => onOpenScene(it.intervention_id)}>
                      Escena
                    </Button>
                  )}
                  {it.status === 'failed' && (
                    <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" icon={<RefreshCw className="size-3" />} disabled={busy}
                      onClick={() => void run(() => budget((c) => api.prepareAnimations(projectId, { use_claude: useClaude, only: [it.intervention_id], confirm_budget: c })), 'Reintentando')}>
                      Reintentar
                    </Button>
                  )}
                  {it.status === 'ready' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      className="h-6 px-2 text-[11px]"
                      icon={it.preview_running ? <Spinner className="size-3" /> : <Eye className="size-3" />}
                      disabled={busy && !it.preview}
                      onClick={() => {
                        if (it.preview) setOpen(it.intervention_id)
                        else {
                          setWaitingPreview(it.intervention_id)
                          void run(() => api.previewAnimation(projectId, it.intervention_id), 'Preparando la vista previa')
                        }
                      }}
                    >
                      {it.preview ? 'Ver' : 'Vista previa'}
                    </Button>
                  )}
                </div>
              </div>
              <p className="mt-0.5 line-clamp-1 text-[11.5px] text-fg-muted">{it.goal}</p>
              {it.warnings?.map((w) => (
                <p key={w.code + w.message} className="mt-1 flex gap-1 text-[11px] text-warning">
                  <CircleAlert className="mt-0.5 size-3 shrink-0" /> {w.message}
                </p>
              ))}
              {it.error && (
                <p className="mt-1 flex gap-1 text-[11px] text-danger">
                  <CircleAlert className="mt-0.5 size-3 shrink-0" /> {it.error}
                </p>
              )}
            </li>
          )
        })}
      </ol>
      <PreviewDialog
        item={opened}
        asset={asset}
        profile={profile}
        layout={layout.data ?? null}
        onClose={() => {
          setOpen(null)
          setWaitingPreview(null)
        }}
      />
    </section>
  )
}
