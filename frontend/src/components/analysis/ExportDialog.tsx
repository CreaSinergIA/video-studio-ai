import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Film, FolderSearch, Play, RotateCcw, Square, Trash, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge, ProgressBar, Spinner } from '@/components/ui/feedback'
import { Field, Segmented, Select, Switch } from '@/components/ui/fields'
import { keys, useExports, useAnimations } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatBytes, formatDateTime, formatDuration, IS_WINDOWS } from '@/lib/format'
import type { Asset, ExportItem, ExportSettings } from '@/lib/types'

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e))

function useDebounced<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return v
}

function ExportRow({ item, onPreview }: { item: ExportItem; onPreview: (e: ExportItem) => void }) {
  const qc = useQueryClient()
  const running = item.status === 'queued' || item.status === 'running'
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.exports(item.project_id) })
    qc.invalidateQueries({ queryKey: keys.jobs })
  }
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      refresh()
    } catch (err) {
      toast.error('No se pudo completar la acción', { description: errText(err) })
    }
  }
  const job = item.job
  return (
    <li className="rounded-xl border border-line bg-surface-2/60 p-3">
      <div className="flex items-start gap-3">
        <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-3 text-fg-muted">
          {running ? <Spinner /> : <Film className="size-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-fg">{item.file_name ?? 'Exportación en curso'}</div>
          <div className="mt-0.5 text-xs text-fg-faint">
            {item.status === 'succeeded' && `${item.width}×${item.height} · ${formatDuration(item.duration)} · ${formatBytes(item.size_bytes)} · `}
            {formatDateTime(item.created_at)}
          </div>
          {running && job && (
            <>
              <div className="mt-1 text-xs text-fg-muted">
                {job.stage ?? 'En cola'} · {Math.round(job.progress * 100)} %
              </div>
              <ProgressBar value={job.progress} className="mt-1.5" label="Progreso de la exportación" />
            </>
          )}
          {item.status === 'failed' && <p className="mt-1 text-xs text-danger">{item.error}</p>}
          {item.status === 'cancelled' && <p className="mt-1 text-xs text-fg-faint">Cancelada.</p>}
        </div>
        <Badge tone={item.status === 'succeeded' ? 'success' : item.status === 'failed' ? 'danger' : 'neutral'}>
          {{ queued: 'En cola', running: 'Exportando', succeeded: 'Lista', failed: 'Error', cancelled: 'Cancelada' }[item.status]}
        </Badge>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {item.status === 'succeeded' && (
          <>
            <Button size="sm" variant="secondary" icon={<Play className="size-3.5" />} onClick={() => onPreview(item)}>
              Ver
            </Button>
            <Button size="sm" variant="ghost" icon={<Film className="size-3.5" />} onClick={() => act(() => api.openExport(item.id))}>
              Abrir
            </Button>
            <Button size="sm" variant="ghost" icon={<FolderSearch className="size-3.5" />} onClick={() => act(() => api.revealExport(item.id))}>
              {IS_WINDOWS ? 'Explorador' : 'Finder'}
            </Button>
            <a
              href={`${item.url}?download=true`}
              download
              className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-fg-muted transition hover:bg-surface-3 hover:text-fg"
            >
              <Download className="size-3.5" /> Descargar
            </a>
          </>
        )}
        {running && job && (
          <Button size="sm" variant="ghost" icon={<Square className="size-3.5" />} onClick={() => act(() => api.cancelJob(job.id))}>
            Cancelar
          </Button>
        )}
        {(item.status === 'failed' || item.status === 'cancelled') && item.job_id && (
          <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" />} onClick={() => act(() => api.retryJob(item.job_id as string))}>
            Reintentar
          </Button>
        )}
        {!running && (
          <Button size="sm" variant="ghost" icon={<Trash className="size-3.5" />} className="ml-auto text-danger hover:text-danger" onClick={() => act(() => api.deleteExport(item.id))}>
            Eliminar
          </Button>
        )}
      </div>
    </li>
  )
}

export function ExportDialog({
  open,
  onOpenChange,
  projectId,
  asset,
  initial,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  projectId: string
  asset: Asset
  initial: ExportSettings
}) {
  const qc = useQueryClient()
  const { data: exports } = useExports(open ? projectId : undefined)
  const [settings, setSettings] = useState<ExportSettings>(initial)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<ExportItem | null>(null)
  const anim = useAnimations(open ? projectId : undefined)
  const approved = anim.data?.approved_version ?? null
  const animatable = (anim.data?.items ?? []).filter((i) => i.status !== 'kept').length
  const [withAnimations, setWithAnimations] = useState(true)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setSettings(initial)
  }
  const debounced = useDebounced(settings)
  const plan = useQuery({
    queryKey: ['export-plan', projectId, debounced],
    queryFn: () => api.exportPlan(projectId, debounced),
    enabled: open,
  })
  const short = Math.min(asset.display_width, asset.display_height)
  const set = <K extends keyof ExportSettings>(k: K, v: ExportSettings[K]) => setSettings((s) => ({ ...s, [k]: v }))

  const start = async () => {
    setBusy(true)
    try {
      await api.createExport(projectId, settings, Boolean(approved) && withAnimations)
      qc.invalidateQueries({ queryKey: keys.exports(projectId) })
      qc.invalidateQueries({ queryKey: keys.jobs })
      qc.invalidateQueries({ queryKey: keys.project(projectId) })
      toast.success('Exportación en marcha')
    } catch (err) {
      toast.error('No se pudo exportar', { description: errText(err) })
    } finally {
      setBusy(false)
    }
  }
  const p = plan.data?.plan
  return (
    <>
      <Dialog
        open={open}
        onOpenChange={onOpenChange}
        size="lg"
        icon={<Download className="size-5" />}
        title="Exportar video"
        description={
          approved && withAnimations
            ? `Video editado: original + animaciones del plan aprobado v${approved} + efectos de sonido + subtítulos con el tratamiento aprobado + audio original. Sin música. El original no se modifica: el resultado es un archivo nuevo en «exports».`
            : 'Video original + subtítulos personalizados + audio original. Sin animaciones, efectos ni música. El original no se modifica: el resultado es un archivo nuevo en «exports».'
        }
      >
        <div className="grid gap-5 pb-3 md:grid-cols-2">
          <div className="divide-y divide-line">
            {approved !== null && (
              <Field
                label="Edición del plan aprobado"
                hint={
                  anim.data?.engine_ready === false && withAnimations
                    ? 'El motor de animaciones no está listo (Ajustes → Animaciones): la exportación con animaciones fallará.'
                    : `v${approved}: ${animatable} animación(es) con efectos y transiciones. Las que falten se generan durante la exportación.`
                }
              >
                <Switch label="Incluir animaciones" checked={withAnimations} onCheckedChange={setWithAnimations} />
              </Field>
            )}
            <Field label="Resolución" hint={short < 1080 ? `Original ${asset.display_width}×${asset.display_height}: no se reescala hacia arriba.` : undefined} stacked>
              <Segmented
                label="Resolución"
                value={settings.resolution}
                onValueChange={(v) => set('resolution', v)}
                options={[
                  { value: 'original', label: `Original (${asset.display_width}×${asset.display_height})` },
                  { value: '1080p', label: '1080p', disabled: short < 1080 },
                  { value: '4k', label: '4K', disabled: short < 2160 },
                ]}
                className="w-full"
              />
            </Field>
            <Field label="Fotogramas por segundo">
              <Select
                label="FPS"
                value={String(settings.fps)}
                onValueChange={(v) => set('fps', v === 'original' ? 'original' : (Number(v) as 24 | 25 | 30 | 50 | 60))}
                options={[{ value: 'original', label: `Original (${Math.round(asset.fps * 100) / 100})` }, ...[24, 25, 30, 50, 60].map((f) => ({ value: String(f), label: `${f} fps` }))]}
              />
            </Field>
            <Field label="Formato">
              <Select
                label="Formato"
                value={settings.format}
                onValueChange={(v) => set('format', v)}
                options={[
                  { value: 'mp4_h264', label: 'MP4 · H.264', disabled: asset.is_hdr, hint: asset.is_hdr ? 'No conserva HDR' : 'Máxima compatibilidad' },
                  { value: 'mp4_hevc', label: 'MP4 · HEVC', hint: 'Menor tamaño; 10 bits si el original lo es' },
                  { value: 'mov_prores', label: 'MOV · ProRes 422', hint: 'Para seguir editando (archivos grandes)' },
                ]}
              />
            </Field>
            <Field label="Calidad" stacked>
              <Segmented label="Calidad" value={settings.quality} onValueChange={(v) => set('quality', v)} options={[{ value: 'high', label: 'Alta' }, { value: 'max', label: 'Máxima' }]} className="w-full" />
            </Field>
            <Field label="Codificador" hint="El hardware (VideoToolbox) dio la misma calidad por tamaño que el software y es 4–25× más rápido en nuestras pruebas." stacked>
              <Segmented label="Codificador" value={settings.encoder} onValueChange={(v) => set('encoder', v)} options={[{ value: 'hardware', label: 'Hardware (rápido)' }, { value: 'software', label: 'Software' }]} className="w-full" />
            </Field>
          </div>
          <div className="space-y-3">
            <div className="rounded-xl border border-line bg-surface-2 p-4 text-sm">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">Resultado</h3>
              {plan.isFetching && !p ? (
                <Spinner />
              ) : plan.data && !plan.data.ok ? (
                <p className="flex gap-2 text-danger">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" />
                  {plan.data.error}
                </p>
              ) : p ? (
                <dl className="space-y-1 text-[13px]">
                  <div className="flex justify-between"><dt className="text-fg-faint">Dimensiones</dt><dd className="tabular">{p.width}×{p.height}</dd></div>
                  <div className="flex justify-between"><dt className="text-fg-faint">FPS</dt><dd>{p.fps === 'original' ? 'Original (incluye FPS variable)' : p.fps}</dd></div>
                  <div className="flex justify-between"><dt className="text-fg-faint">Códec</dt><dd>{p.video_codec.toUpperCase()} · {p.encoder}</dd></div>
                  <div className="flex justify-between"><dt className="text-fg-faint">Píxel</dt><dd>{p.pix_fmt}</dd></div>
                  <div className="flex justify-between"><dt className="text-fg-faint">Subtítulos</dt><dd>{plan.data?.subtitles ? 'Integrados' : 'No (sin transcripción o desactivados)'}</dd></div>
                  <div className="flex justify-between"><dt className="text-fg-faint">Tamaño estimado</dt><dd>≤ {formatBytes(p.estimated_bytes)}</dd></div>
                </dl>
              ) : null}
              {p?.warnings.map((w) => (
                <p key={w} className="mt-2 flex gap-2 text-xs text-warning">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
                  {w}
                </p>
              ))}
              <p className="mt-3 text-[11px] leading-snug text-fg-faint">Toda exportación recodifica el video: no es una copia sin pérdidas matemáticas, sino una codificación de alta fidelidad.</p>
            </div>
            <Button variant="primary" size="lg" className="w-full justify-center" loading={busy} disabled={!plan.data?.ok || anim.isPending} icon={<Download className="size-4" />} onClick={start}>
              Exportar
            </Button>
          </div>
        </div>
        {exports && exports.length > 0 && (
          <section className="mt-2 border-t border-line pb-2 pt-4">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">Exportaciones del proyecto</h3>
            <ul className="space-y-2">
              {exports.map((e) => (
                <ExportRow key={e.id} item={e} onPreview={setPreview} />
              ))}
            </ul>
          </section>
        )}
      </Dialog>
      <Dialog open={preview !== null} onOpenChange={(o) => !o && setPreview(null)} size="xl" title={preview?.file_name ?? 'Vista previa'} description="Reproducción del archivo exportado.">
        {preview?.url && (
          <video src={preview.url} controls autoPlay className="mx-auto max-h-[70vh] w-auto rounded-lg bg-black" aria-label="Vista previa de la exportación" />
        )}
      </Dialog>
    </>
  )
}
