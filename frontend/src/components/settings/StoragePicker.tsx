import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronLeft,
  CircleAlert,
  CircleCheck,
  Folder,
  FolderOpen,
  HardDrive,
  Info,
  TriangleAlert,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/fields'
import { Spinner } from '@/components/ui/feedback'
import { keys, useSystemInfo } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'
import type { StorageCandidate } from '@/lib/types'

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}

function Report({ report, onUseSuggested }: { report: StorageCandidate; onUseSuggested: (p: string) => void }) {
  const usage =
    report.total_bytes && report.free_bytes !== null
      ? 1 - report.free_bytes / report.total_bytes
      : null
  return (
    <div className="space-y-2.5 rounded-xl border border-line bg-surface-2 p-4 text-sm">
      <div className="flex items-center gap-2">
        {report.can_use ? (
          <CircleCheck className="size-4 text-success" />
        ) : (
          <CircleAlert className="size-4 text-danger" />
        )}
        <span className="font-medium text-fg">
          {report.can_use
            ? report.has_marker
              ? `Almacenamiento de Video Studio existente · ${report.project_count} proyecto(s)`
              : report.exists
                ? 'Carpeta válida'
                : 'Se creará esta carpeta'
            : 'No se puede usar esta ruta'}
        </span>
      </div>
      {usage !== null && (
        <div>
          <div className="mb-1 flex justify-between text-xs text-fg-muted">
            <span>
              {report.volume_name ? `Disco «${report.volume_name}»` : 'Disco del sistema'}
              {report.is_external && ' · externo'}
            </span>
            <span className="tabular">
              {formatBytes(report.free_bytes)} libres de {formatBytes(report.total_bytes)}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-4">
            <div
              className={cn('h-full rounded-full', usage > 0.9 ? 'bg-danger' : usage > 0.75 ? 'bg-warning' : 'bg-accent')}
              style={{ width: `${usage * 100}%` }}
            />
          </div>
        </div>
      )}
      {report.errors.map((e) => (
        <p key={e} className="flex gap-2 text-danger">
          <CircleAlert className="mt-0.5 size-3.5 shrink-0" />
          {e}
        </p>
      ))}
      {report.warnings.map((w) => (
        <p key={w} className="flex gap-2 text-warning">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {w}
            {report.suggested_path && w.includes('subcarpeta') && (
              <button
                type="button"
                onClick={() => onUseSuggested(report.suggested_path as string)}
                className="ml-1.5 font-semibold underline underline-offset-2 hover:text-fg"
              >
                Usar …/VideoStudio
              </button>
            )}
          </span>
        </p>
      ))}
    </div>
  )
}

export function StoragePicker({
  initialPath,
  onConfigured,
  submitLabel = 'Usar esta carpeta',
}: {
  initialPath?: string | null
  onConfigured?: () => void
  submitLabel?: string
}) {
  const qc = useQueryClient()
  const { data: system } = useSystemInfo()
  const [path, setPath] = useState(initialPath ?? '')
  const [browsePath, setBrowsePath] = useState<string | undefined>(undefined)
  const [saving, setSaving] = useState(false)
  const [picking, setPicking] = useState(false)
  const debounced = useDebounced(path.trim(), 350)

  const validation = useQuery({
    queryKey: ['storage-validate', debounced],
    queryFn: () => api.validateStorage(debounced),
    enabled: debounced.startsWith('/') || debounced.startsWith('~'),
    retry: false,
  })
  const browse = useQuery({
    queryKey: ['storage-browse', browsePath ?? ''],
    queryFn: () => api.browse(browsePath),
    retry: false,
  })

  const pickNative = async () => {
    setPicking(true)
    try {
      const res = await api.pickFolder()
      if (res.path) {
        setPath(res.path)
        setBrowsePath(res.path)
      }
    } catch (err) {
      toast.error('No se pudo abrir Finder', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setPicking(false)
    }
  }

  const submit = async () => {
    setSaving(true)
    try {
      const res = await api.configureStorage(path.trim())
      qc.setQueryData(keys.storage, res.status)
      qc.invalidateQueries({ queryKey: keys.projects })
      qc.invalidateQueries({ queryKey: keys.locations })
      toast.success('Almacenamiento configurado', {
        description:
          res.adopted_projects > 0
            ? `Se recuperaron ${res.adopted_projects} proyecto(s) existentes en esta carpeta.`
            : res.status.path ?? undefined,
      })
      onConfigured?.()
    } catch (err) {
      toast.error('No se pudo configurar', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setSaving(false)
    }
  }

  const report = validation.data
  const isValidating = validation.isFetching || (path.trim() !== debounced && path.trim().length > 0)

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <HardDrive className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-faint" />
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/Volumes/MiDisco/VideoStudio"
            className="h-10 pl-9 font-mono text-[13px]"
            aria-label="Ruta de la carpeta de almacenamiento"
            spellCheck={false}
            autoCorrect="off"
            autoCapitalize="off"
          />
          {isValidating && <Spinner className="absolute right-3 top-1/2 -translate-y-1/2 text-fg-faint" />}
        </div>
        {system?.native_dialogs && (
          <Button size="lg" variant="secondary" onClick={pickNative} loading={picking} icon={<FolderOpen className="size-4" />}>
            Elegir en Finder
          </Button>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-line bg-surface-2">
        <div className="flex items-center gap-2 border-b border-line px-3 py-2">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Carpeta superior"
            disabled={!browse.data?.parent}
            onClick={() => setBrowsePath(browse.data?.parent ?? undefined)}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg-muted">{browse.data?.path ?? '…'}</span>
          {browse.data && (
            <Button size="sm" variant="ghost" onClick={() => setPath(browse.data.path)}>
              Seleccionar esta
            </Button>
          )}
        </div>
        <div className="flex h-52">
          <ul className="w-44 shrink-0 space-y-0.5 overflow-y-auto border-r border-line p-1.5" aria-label="Accesos rápidos">
            {browse.data?.shortcuts.map((s) => (
              <li key={s.path}>
                <button
                  type="button"
                  onClick={() => setBrowsePath(s.path)}
                  className="flex w-full items-center gap-2 truncate rounded-lg px-2 py-1.5 text-left text-xs text-fg-muted hover:bg-surface-3 hover:text-fg"
                >
                  <HardDrive className="size-3.5 shrink-0" />
                  <span className="truncate">{s.name}</span>
                </button>
              </li>
            ))}
          </ul>
          <ul className="min-w-0 flex-1 overflow-y-auto p-1.5" aria-label="Carpetas">
            {browse.isError && (
              <li className="p-3 text-xs text-danger">{(browse.error as Error).message}</li>
            )}
            {browse.data?.entries.length === 0 && (
              <li className="p-3 text-xs text-fg-faint">Sin subcarpetas.</li>
            )}
            {browse.data?.entries.map((e) => (
              <li key={e.path}>
                <button
                  type="button"
                  onClick={() => setPath(e.path)}
                  onDoubleClick={() => setBrowsePath(e.path)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-surface-3',
                    path === e.path ? 'bg-accent-soft text-fg' : 'text-fg-muted',
                  )}
                  title="Clic para seleccionar · doble clic para abrir"
                >
                  <Folder className={cn('size-4 shrink-0', e.is_storage ? 'text-accent' : 'text-fg-faint')} />
                  <span className="truncate">{e.name}</span>
                  {e.is_storage && <span className="ml-auto shrink-0 text-[10.5px] text-accent">Video Studio</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="flex items-start gap-2 text-xs leading-relaxed text-fg-faint">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        Clic para seleccionar una carpeta, doble clic para entrar. Si la carpeta no existe se creará
        (solo el último nivel). Recomendado: una carpeta dedicada en tu disco externo.
      </p>

      {report && <Report report={report} onUseSuggested={(p) => setPath(p)} />}
      {validation.isError && (
        <p className="text-sm text-danger">{(validation.error as Error).message}</p>
      )}

      <div className="flex justify-end">
        <Button variant="primary" size="lg" disabled={!report?.can_use || isValidating} loading={saving} onClick={submit}>
          {submitLabel}
        </Button>
      </div>
    </div>
  )
}
