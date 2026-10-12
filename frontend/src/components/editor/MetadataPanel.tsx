import { useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, FolderSearch, RefreshCw, ShieldCheck, Wand } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge } from '@/components/ui/feedback'
import { keys } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import {
  codecLabel,
  formatBitrate,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatFps,
  formatResolution,
  ORIENTATION_LABEL,
  resolutionLabel,
} from '@/lib/format'
import type { Asset, ProjectDetail } from '@/lib/types'

function Row({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 py-1.5 text-[13px]">
      <dt className="text-fg-faint">{label}</dt>
      <dd className={mono ? 'truncate font-mono text-xs leading-5 text-fg' : 'text-fg'}>{children}</dd>
    </div>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-b border-line px-5 py-4 last:border-b-0">
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">{title}</h3>
      <dl>{children}</dl>
    </div>
  )
}

export function MetadataPanel({ project, asset }: { project: ProjectDetail; asset: Asset }) {
  const qc = useQueryClient()
  const run = async (fn: () => Promise<unknown>, success?: string) => {
    try {
      await fn()
      qc.invalidateQueries({ queryKey: keys.jobs })
      qc.invalidateQueries({ queryKey: keys.project(project.id) })
      if (success) toast.success(success)
    } catch (err) {
      toast.error('No se pudo completar la acción', { description: err instanceof ApiError ? err.message : String(err) })
    }
  }
  const available = project.storage_available
  const busy = Boolean(project.active_job)

  return (
    <div>
      <div className="flex flex-wrap gap-2 border-b border-line px-5 py-4">
        <Button size="sm" variant="secondary" icon={<FolderSearch className="size-3.5" />} disabled={!available} onClick={() => run(() => api.reveal(asset.id))}>
          Mostrar en Finder
        </Button>
        <Button size="sm" variant="secondary" icon={<ShieldCheck className="size-3.5" />} disabled={!available || busy} onClick={() => run(() => api.verify(asset.id), 'Verificación en curso')}>
          Verificar integridad
        </Button>
        <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} disabled={!available || busy} onClick={() => run(() => api.reprocess(asset.id), 'Regenerando miniaturas y forma de onda')}>
          Regenerar vistas
        </Button>
        {!asset.proxy_ready && (
          <Button size="sm" variant="ghost" icon={<Wand className="size-3.5" />} disabled={!available || busy} onClick={() => run(() => api.requestProxy(asset.id), 'Creando proxy de reproducción')}>
            Crear proxy
          </Button>
        )}
      </div>

      <Group title="Archivo">
        <Row label="Nombre">{asset.original_filename}</Row>
        <Row label="Contenedor">
          {asset.container.toUpperCase()}
          {asset.major_brand && <span className="text-fg-faint"> · marca «{asset.major_brand}»</span>}
        </Row>
        <Row label="Tamaño">{formatBytes(asset.size_bytes, 2)}</Row>
        <Row label="Importado">{formatDateTime(asset.created_at)}</Row>
        {asset.creation_time && <Row label="Grabado">{formatDateTime(asset.creation_time)}</Row>}
        <Row label="Ubicación" mono>
          <span title={`${project.storage_path}/${asset.file_rel}`}>{asset.file_rel}</span>
        </Row>
      </Group>

      <Group title="Video">
        <Row label="Resolución">
          {formatResolution(asset)} <span className="text-fg-faint">· {resolutionLabel(asset)}</span>
        </Row>
        <Row label="Orientación">
          {ORIENTATION_LABEL[asset.orientation]}
          {asset.rotation !== 0 && <span className="text-fg-faint"> · rotación {asset.rotation}° (codificado {asset.width}×{asset.height})</span>}
        </Row>
        <Row label="Duración">
          {formatDuration(asset.duration)} <span className="text-fg-faint">· {asset.duration.toFixed(3)} s</span>
        </Row>
        <Row label="Fotogramas">
          {formatFps(asset.fps)}
          <span className="text-fg-faint">
            {' '}
            · {asset.fps_num}/{asset.fps_den}
            {asset.frame_count ? ` · ${asset.frame_count.toLocaleString('es')} fotogramas` : ''}
          </span>
        </Row>
        <Row label="Códec">
          {codecLabel(asset.video_codec)}
          {asset.video_profile && <span className="text-fg-faint"> · {asset.video_profile}</span>}
        </Row>
        <Row label="Píxel">
          {asset.pix_fmt ?? '—'}
          {asset.bit_depth && <span className="text-fg-faint"> · {asset.bit_depth} bits</span>}
          {asset.is_hdr && (
            <Badge tone="accent" className="ml-2 h-5">
              HDR
            </Badge>
          )}
        </Row>
        <Row label="Tasa de bits">{formatBitrate(asset.bit_rate)}</Row>
        <Row label="Reproducción">
          {asset.playback === 'proxy' ? (
            <span>Proxy H.264 (el códec original no es compatible con el navegador)</span>
          ) : asset.playback === 'original' ? (
            <span>Archivo original{asset.proxy_ready ? ' · proxy disponible' : ''}</span>
          ) : (
            <span className="text-warning">{available ? 'Requiere proxy' : 'Almacenamiento desconectado'}</span>
          )}
        </Row>
      </Group>

      <Group title={`Audio · ${asset.audio_tracks.length} pista${asset.audio_tracks.length === 1 ? '' : 's'}`}>
        {asset.audio_tracks.length === 0 && <p className="py-1.5 text-[13px] text-fg-muted">El video no tiene pistas de audio.</p>}
        {asset.audio_tracks.map((t, i) => (
          <Row key={t.index} label={`Pista ${i + 1}`}>
            {codecLabel(t.codec)}
            <span className="text-fg-faint">
              {' '}
              · {t.channel_layout ?? `${t.channels ?? '?'} canales`}
              {t.sample_rate ? ` · ${(t.sample_rate / 1000).toFixed(1)} kHz` : ''}
              {t.bit_rate ? ` · ${formatBitrate(t.bit_rate)}` : ''}
              {t.language && t.language !== 'und' ? ` · ${t.language}` : ''}
            </span>
          </Row>
        ))}
      </Group>

      <Group title="Integridad">
        <Row label="SHA-256" mono>
          <button
            type="button"
            className="inline-flex max-w-full items-center gap-1.5 truncate hover:text-accent"
            onClick={() => {
              void navigator.clipboard.writeText(asset.sha256)
              toast.success('Huella SHA-256 copiada')
            }}
            title="Copiar huella completa"
          >
            <span className="truncate">{asset.sha256}</span>
            <Copy className="size-3 shrink-0" />
          </button>
        </Row>
        <Row label="Verificado">
          {asset.verified_at ? (
            <span className="text-success">Íntegro · {formatDateTime(asset.verified_at)}</span>
          ) : (
            <span className="text-fg-muted">Huella registrada al importar</span>
          )}
        </Row>
      </Group>
      <RenderCache projectId={project.id} />
    </div>
  )
}

/** Caché de render del proyecto: lo que ocupa y limpieza segura de lo que no está en uso. */
function RenderCache({ projectId }: { projectId: string }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['render-cache', projectId], queryFn: () => api.renderCache(projectId) })
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  if (!data) return null
  const clean = async () => {
    setBusy(true)
    try {
      const r = await api.cleanRenderCache(projectId)
      toast.success(`Liberados ${formatBytes(r.freed_bytes)}`, { description: 'Se regenerarán solo si vuelven a hacer falta (sin solicitudes a Claude).' })
      await qc.invalidateQueries({ queryKey: ['render-cache', projectId] })
      setConfirming(false)
    } catch (err) {
      toast.error('No se pudo limpiar', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Group title="Caché de animaciones">
      <Row label="Clips">
        {data.clips.count} · {formatBytes(data.clips.bytes)}
      </Row>
      <Row label="Vistas previas">
        {data.previews.count} · {formatBytes(data.previews.bytes)}
      </Row>
      <Row label="Sin uso">{formatBytes(data.unused_bytes)}</Row>
      <p className="mt-1 text-[11.5px] leading-relaxed text-fg-faint">
        Solo archivos regenerables que no usa la versión aprobada actual ni una escena en uso o propuesta. Nunca se tocan el original, los planes ni las exportaciones.
      </p>
      <Button className="mt-2" size="sm" variant="secondary" disabled={data.unused_bytes === 0} onClick={() => setConfirming(true)}>
        Liberar {formatBytes(data.unused_bytes)}
      </Button>
      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        size="sm"
        title="¿Liberar la caché sin uso?"
        description={`Se borrarán ${data.clips.unused_count} clips y ${data.previews.unused_count} vistas previas que no usa la versión aprobada actual (${formatBytes(data.unused_bytes)}). Si vuelves a una versión anterior, se regenerarán automáticamente.`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              Cancelar
            </Button>
            <Button variant="primary" loading={busy} onClick={() => void clean()}>
              Liberar espacio
            </Button>
          </>
        }
      />
    </Group>
  )
}

