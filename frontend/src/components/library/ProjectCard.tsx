import { useNavigate } from 'react-router'
import {
  CircleAlert,
  Clock,
  Ellipsis,
  FolderSearch,
  ImageOff,
  Pencil,
  Play,
  RectangleHorizontal,
  RectangleVertical,
  Square,
  Trash,
  Unplug,
  Upload,
} from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import {
  formatBytes,
  formatDuration,
  formatFps,
  formatRelative,
  formatResolution,
  ORIENTATION_LABEL,
  resolutionLabel,
  STYLE_META,
} from '@/lib/format'
import type { ProjectSummary } from '@/lib/types'
import { Badge, ProgressBar } from '@/components/ui/feedback'
import { Menu } from '@/components/ui/Menu'

export interface CardActions {
  onRename: (p: ProjectSummary) => void
  onDelete: (p: ProjectSummary) => void
}

const ORIENTATION_ICON = {
  vertical: <RectangleVertical className="size-3" />,
  horizontal: <RectangleHorizontal className="size-3" />,
  square: <Square className="size-3" />,
}

export function Thumbnail({ project, className }: { project: ProjectSummary; className?: string }) {
  const thumb = project.source?.thumbnail_url
  const available = project.storage_available
  if (!thumb || !available) {
    return (
      <div className={cn('grid place-items-center bg-surface-2 text-fg-faint', className)}>
        {!available ? (
          <Unplug className="size-6" />
        ) : project.status === 'empty' ? (
          <Upload className="size-6" />
        ) : project.status === 'error' ? (
          <ImageOff className="size-6" />
        ) : (
          <div className="skeleton absolute inset-0" />
        )}
      </div>
    )
  }
  const vertical = project.source?.orientation === 'vertical'
  return (
    <div className={cn('relative overflow-hidden bg-stage', className)}>
      {vertical && (
        <img
          src={thumb}
          alt=""
          aria-hidden
          className="absolute inset-0 size-full scale-125 object-cover opacity-40 blur-2xl"
        />
      )}
      <img
        src={thumb}
        alt={`Miniatura de ${project.name}`}
        loading="lazy"
        className={cn('relative size-full', vertical ? 'object-contain' : 'object-cover')}
      />
    </div>
  )
}

function StatusOverlay({ project }: { project: ProjectSummary }) {
  const job = project.active_job
  if (project.status === 'unavailable')
    return (
      <Badge tone="warning" icon={<Unplug className="size-3" />} className="backdrop-blur">
        Disco desconectado
      </Badge>
    )
  if (project.status === 'error')
    return (
      <Badge tone="danger" icon={<CircleAlert className="size-3" />}>
        Error
      </Badge>
    )
  if (project.status === 'empty') return <Badge>Sin video</Badge>
  if (job || project.status === 'processing' || project.status === 'importing')
    return (
      <Badge tone="accent" className="bg-black/50 backdrop-blur">
        {job ? `${Math.round(job.progress * 100)} %` : 'Preparando…'}
      </Badge>
    )
  return null
}

function menuItems(project: ProjectSummary, actions: CardActions, open: () => void) {
  return [
    { label: 'Abrir', icon: <Play />, onSelect: open },
    { label: 'Renombrar', icon: <Pencil />, onSelect: () => actions.onRename(project) },
    {
      label: 'Mostrar en Finder',
      icon: <FolderSearch />,
      disabled: !project.source || !project.storage_available,
      onSelect: () => project.source && void api.reveal(project.source.id),
    },
    {
      label: project.storage_available ? 'Eliminar…' : 'Quitar de la biblioteca…',
      icon: <Trash />,
      danger: true,
      separatorBefore: true,
      onSelect: () => actions.onDelete(project),
    },
  ]
}

export function ProjectCard({ project, actions }: { project: ProjectSummary; actions: CardActions }) {
  const navigate = useNavigate()
  const src = project.source
  const open = () => navigate(`/projects/${project.id}`)
  const style = STYLE_META[project.style_id]
  const job = project.active_job

  return (
    <article className="group relative animate-rise">
      <button
        type="button"
        onClick={open}
        className="block w-full overflow-hidden rounded-2xl border border-line bg-surface-1 text-left shadow-panel transition duration-300 ease-out hover:-translate-y-0.5 hover:border-line-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        aria-label={`Abrir proyecto ${project.name}`}
      >
        <div className="relative aspect-[16/10]">
          <Thumbnail project={project} className="absolute inset-0" />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/55 via-transparent to-black/10" />
          <div className="absolute left-3 top-3 flex gap-1.5">
            {src && (
              <Badge className="border-white/10 bg-black/45 text-white/90 backdrop-blur" icon={ORIENTATION_ICON[src.orientation]}>
                {ORIENTATION_LABEL[src.orientation]}
              </Badge>
            )}
          </div>
          <div className="absolute right-3 top-3">
            <StatusOverlay project={project} />
          </div>
          {src && (
            <div className="absolute bottom-3 right-3 rounded-md bg-black/60 px-1.5 py-0.5 text-[11.5px] font-semibold tabular text-white backdrop-blur">
              {formatDuration(src.duration)}
            </div>
          )}
          {project.status === 'ready' && (
            <div className="absolute inset-0 grid place-items-center opacity-0 transition duration-200 group-hover:opacity-100">
              <div className="grid size-12 place-items-center rounded-full bg-white/15 text-white backdrop-blur-md">
                <Play className="ml-0.5 size-5 fill-current" />
              </div>
            </div>
          )}
          {job && (
            <div className="absolute inset-x-3 bottom-3 right-16">
              <ProgressBar value={job.progress} className="h-1 bg-white/15" label={job.stage ?? job.label} />
            </div>
          )}
        </div>
        <div className="px-4 pb-4 pt-3.5">
          <h3 className="truncate pr-8 text-[14.5px] font-semibold tracking-tight text-fg">{project.name}</h3>
          <p className="mt-1 truncate text-xs text-fg-muted tabular">
            {src ? (
              <>
                {formatResolution(src)} · {resolutionLabel(src)} · {formatFps(src.fps)} · {formatBytes(src.size_bytes)}
              </>
            ) : job ? (
              (job.stage ?? job.label)
            ) : (
              'Proyecto vacío · importa un video'
            )}
          </p>
          <div className="mt-3 flex items-center justify-between text-[11.5px] text-fg-faint">
            <span className="flex items-center gap-1.5">
              <span className="size-1.5 rounded-full ring-1 ring-line-strong" style={{ background: style.color }} />
              {style.name}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="size-3" />
              {formatRelative(project.last_opened_at ?? project.created_at)}
            </span>
          </div>
        </div>
      </button>
      <div className="absolute bottom-[60px] right-3 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
        <Menu
          items={menuItems(project, actions, open)}
          trigger={
            <button
              type="button"
              aria-label={`Acciones de ${project.name}`}
              className="grid size-8 place-items-center rounded-lg border border-line bg-surface-2/90 text-fg-muted backdrop-blur transition hover:text-fg"
            >
              <Ellipsis className="size-4" />
            </button>
          }
        />
      </div>
    </article>
  )
}

export function ProjectRow({ project, actions }: { project: ProjectSummary; actions: CardActions }) {
  const navigate = useNavigate()
  const src = project.source
  const open = () => navigate(`/projects/${project.id}`)
  const style = STYLE_META[project.style_id]
  return (
    <div
      role="row"
      className="group grid grid-cols-[88px_minmax(0,2.2fr)_1fr_0.8fr_0.9fr_1fr_44px] items-center gap-4 rounded-xl px-3 py-2 transition hover:bg-surface-2"
    >
      <button type="button" onClick={open} className="relative aspect-video overflow-hidden rounded-lg border border-line" aria-label={`Abrir ${project.name}`}>
        <Thumbnail project={project} className="absolute inset-0" />
      </button>
      <button type="button" onClick={open} className="min-w-0 text-left">
        <div className="truncate text-sm font-medium text-fg group-hover:underline">{project.name}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-faint">
          <span className="size-1.5 rounded-full ring-1 ring-line-strong" style={{ background: style.color }} />
          {style.name}
        </div>
      </button>
      <div className="text-xs tabular text-fg-muted">{src ? `${formatResolution(src)} · ${formatFps(src.fps)}` : '—'}</div>
      <div className="text-xs text-fg-muted">{src ? ORIENTATION_LABEL[src.orientation] : '—'}</div>
      <div className="text-xs tabular text-fg-muted">{src ? formatDuration(src.duration) : '—'}</div>
      <div className="flex items-center gap-2 text-xs text-fg-faint">
        <StatusOverlay project={project} />
        {project.status === 'ready' && formatRelative(project.last_opened_at ?? project.created_at)}
      </div>
      <Menu
        items={menuItems(project, actions, open)}
        trigger={
          <button
            type="button"
            aria-label={`Acciones de ${project.name}`}
            className="grid size-8 place-items-center rounded-lg text-fg-faint transition hover:bg-surface-3 hover:text-fg"
          >
            <Ellipsis className="size-4" />
          </button>
        }
      />
    </div>
  )
}
