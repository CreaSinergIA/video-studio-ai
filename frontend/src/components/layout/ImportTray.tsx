import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ChevronDown, CircleAlert, CircleCheck, FileVideoCamera, X } from 'lucide-react'
import { ProgressBar, Spinner } from '@/components/ui/feedback'
import { useImporter, type UploadItem } from '@/hooks/importer-context'
import { useJobs } from '@/hooks/queries'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'
import type { Job } from '@/lib/types'

const STATUS_LABEL: Record<UploadItem['status'], string> = {
  queued: 'En cola',
  checking: 'Comprobando…',
  confirm: 'Esperando confirmación',
  uploading: 'Subiendo',
  finalizing: 'Validando video…',
  done: 'Importado',
  error: 'Error',
  cancelled: 'Cancelado',
}

function TrayRow({ item, job }: { item: UploadItem; job?: Job }) {
  const { cancel, dismiss } = useImporter()
  const navigate = useNavigate()
  const active = ['queued', 'checking', 'confirm', 'uploading', 'finalizing'].includes(item.status)
  // Tras la subida, mostrar la tarea del servidor (copia o preparación).
  const jobActive = job && (job.status === 'queued' || job.status === 'running')
  const progress = jobActive ? job.progress : item.progress
  let label = STATUS_LABEL[item.status]
  if (item.source === 'path' && item.status === 'uploading') {
    label = job ? (job.stage ?? job.label) : 'Copiando…'
    if (job?.status === 'succeeded') label = 'Importado'
    if (job?.status === 'failed') label = job.error ?? 'Error'
  } else if (item.status === 'done' && jobActive) {
    label = job.stage ?? 'Preparando video…'
  } else if (item.status === 'done' && job?.status === 'succeeded') {
    label = 'Listo para editar'
  }
  const failed = item.status === 'error' || job?.status === 'failed'
  const finished =
    !failed && (item.status === 'done' || job?.status === 'succeeded') && !jobActive
  const projectId = item.projectId ?? (job?.result?.project_id as string | undefined)

  return (
    <li className="group flex items-start gap-3 px-4 py-3">
      <div
        className={cn(
          'mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg',
          failed ? 'bg-danger/10 text-danger' : finished ? 'bg-success/10 text-success' : 'bg-surface-3 text-fg-muted',
        )}
      >
        {failed ? (
          <CircleAlert className="size-4" />
        ) : finished ? (
          <CircleCheck className="size-4" />
        ) : active || jobActive ? (
          <Spinner className="size-4" />
        ) : (
          <FileVideoCamera className="size-4" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!projectId}
            onClick={() => projectId && navigate(`/projects/${projectId}`)}
            className="min-w-0 truncate text-left text-[13px] font-medium text-fg enabled:hover:underline"
          >
            {item.name}
          </button>
          {item.size > 0 && <span className="shrink-0 text-[11px] text-fg-faint">{formatBytes(item.size)}</span>}
        </div>
        <div className={cn('mt-0.5 truncate text-xs', failed ? 'text-danger' : 'text-fg-muted')}>
          {failed ? (item.error ?? job?.error ?? label) : item.status === 'cancelled' ? (item.error ?? label) : label}
          {(item.status === 'uploading' || jobActive) && ` · ${Math.round(progress * 100)} %`}
        </div>
        {(item.status === 'uploading' || item.status === 'finalizing' || jobActive) && (
          <ProgressBar value={progress} className="mt-2" label={`Progreso de ${item.name}`} />
        )}
      </div>
      {/* Con el archivo ya enviado (validando) la importación no puede cancelarse. */}
      {item.status !== 'finalizing' && <button
        type="button"
        onClick={() => (active || jobActive ? cancel(item.id) : dismiss(item.id))}
        className="grid size-7 shrink-0 place-items-center rounded-md text-fg-faint transition hover:bg-surface-3 hover:text-fg"
        aria-label={active || jobActive ? `Cancelar ${item.name}` : `Quitar ${item.name} de la lista`}
        title={active || jobActive ? 'Cancelar' : 'Quitar'}
      >
        <X className="size-3.5" />
      </button>}
    </li>
  )
}

export function ImportTray() {
  const { items } = useImporter()
  const { data: jobs } = useJobs()
  const [collapsed, setCollapsed] = useState(false)
  const jobById = new Map((jobs ?? []).map((j) => [j.id, j]))
  const activeCount = items.filter((it) => {
    const job = it.jobId ? jobById.get(it.jobId) : undefined
    return (
      ['queued', 'checking', 'confirm', 'uploading', 'finalizing'].includes(it.status) ||
      (job && (job.status === 'queued' || job.status === 'running'))
    )
  }).length

  // Una importación nueva vuelve a desplegar la bandeja.
  const [prevActive, setPrevActive] = useState(activeCount)
  if (activeCount !== prevActive) {
    setPrevActive(activeCount)
    if (activeCount > prevActive) setCollapsed(false)
  }

  if (!items.length) return null
  return (
    <div className="fixed bottom-5 right-5 z-40 w-[360px] overflow-hidden rounded-2xl border border-line-strong bg-surface-1/95 shadow-panel backdrop-blur-xl animate-rise">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 border-b border-line px-4 py-3 text-left"
        aria-expanded={!collapsed}
      >
        <span className="text-[13px] font-semibold text-fg">Importaciones</span>
        <span className="text-xs text-fg-faint">
          {activeCount > 0 ? `${activeCount} en curso` : 'Completadas'}
        </span>
        <ChevronDown className={cn('ml-auto size-4 text-fg-faint transition', collapsed && '-rotate-90')} />
      </button>
      {!collapsed && (
        <ul className="max-h-80 divide-y divide-line overflow-y-auto">
          {items.map((item) => (
            <TrayRow key={item.id} item={item} job={item.jobId ? jobById.get(item.jobId) : undefined} />
          ))}
        </ul>
      )}
    </div>
  )
}
