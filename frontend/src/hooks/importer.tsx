import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ApiError, api } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import type { Duplicate } from '@/lib/types'
import { hasSupportedExtension, quickHash, uploadFile, type UploadHandle } from '@/lib/upload'
import { ImporterContext, type ImportTarget, type UploadItem } from './importer-context'
import { keys, useSystemInfo } from './queries'


interface PendingConfirm {
  name: string
  duplicates: Duplicate[]
  resolve: (choice: 'import' | 'skip') => void
}

let counter = 0
const nextId = () => `up_${Date.now().toString(36)}_${counter++}`

export function ImporterProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { data: system } = useSystemInfo()
  const [items, setItems] = useState<UploadItem[]>([])
  // Cola de confirmaciones: varias importaciones pueden preguntar a la vez.
  const [confirms, setConfirms] = useState<PendingConfirm[]>([])
  const confirm = confirms[0] ?? null
  const answer = (choice: 'import' | 'skip') => {
    if (!confirm) return
    confirm.resolve(choice)
    setConfirms((list) => list.slice(1))
  }
  const handles = useRef(new Map<string, UploadHandle>())
  const cancelled = useRef(new Set<string>())
  const queue = useRef<Promise<void>>(Promise.resolve())
  const inputRef = useRef<HTMLInputElement>(null)
  const inputTarget = useRef<ImportTarget>({})

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...changes } : it)))
  }, [])

  const askDuplicate = useCallback(
    (name: string, duplicates: Duplicate[]) =>
      new Promise<'import' | 'skip'>((resolve) =>
        setConfirms((list) => [...list, { name, duplicates, resolve }]),
      ),
    [],
  )

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: keys.projects })
    qc.invalidateQueries({ queryKey: keys.jobs })
  }, [qc])

  const processFile = useCallback(
    async (id: string, file: File, target: ImportTarget) => {
      if (cancelled.current.has(id)) return
      try {
        patch(id, { status: 'checking' })
        const hash = await quickHash(file)
        const check = await api.checkImport({
          filename: file.name,
          size_bytes: file.size,
          quick_hash: hash,
          project_id: target.projectId ?? null,
        })
        if (!check.ok) throw new ApiError(409, 'check_failed', check.errors.join(' '))
        let allowDuplicate = false
        if (check.duplicates.length) {
          patch(id, { status: 'confirm' })
          const choice = await askDuplicate(file.name, check.duplicates)
          if (choice === 'skip') {
            patch(id, { status: 'cancelled', error: 'Omitido: ya estaba importado.' })
            return
          }
          allowDuplicate = true
        }
        if (cancelled.current.has(id)) return
        patch(id, { status: 'uploading', progress: 0 })
        const handle = uploadFile(
          file,
          { projectId: target.projectId, allowDuplicate },
          (fraction) => {
            patch(id, {
              progress: fraction,
              status: fraction >= 1 ? 'finalizing' : 'uploading',
            })
          },
        )
        handles.current.set(id, handle)
        const result = await handle.promise
        handles.current.delete(id)
        patch(id, {
          status: 'done',
          progress: 1,
          projectId: result.project.id,
          jobId: result.job?.id,
        })
        refresh()
      } catch (err) {
        handles.current.delete(id)
        const error = err instanceof ApiError ? err : new ApiError(0, 'unknown', String(err))
        if (error.code === 'upload_cancelled' || cancelled.current.has(id)) {
          patch(id, { status: 'cancelled', error: 'Subida cancelada.' })
        } else {
          patch(id, { status: 'error', error: error.message })
          toast.error(`No se pudo importar «${file.name}»`, { description: error.message })
        }
      }
    },
    [askDuplicate, patch, refresh],
  )

  const importFiles = useCallback(
    (fileList: File[] | FileList, target: ImportTarget = {}) => {
      const files = Array.from(fileList)
      if (!files.length) return
      const accepted: [string, File][] = []
      for (const file of files) {
        if (!hasSupportedExtension(file.name)) {
          toast.error(`«${file.name}» no es compatible`, {
            description: 'Solo se admiten videos MP4 y MOV.',
          })
          continue
        }
        if (file.size === 0) {
          toast.error(`«${file.name}» está vacío`)
          continue
        }
        accepted.push([nextId(), file])
      }
      if (target.projectId && accepted.length > 1) {
        toast.error('Un proyecto admite un solo video de origen', {
          description: 'Se importará solo el primero.',
        })
        accepted.splice(1)
      }
      setItems((prev) => [
        ...accepted.map(([id, file]) => ({
          id,
          name: file.name,
          size: file.size,
          status: 'queued' as const,
          progress: 0,
          source: 'browser' as const,
        })),
        ...prev,
      ])
      // Subidas en serie: evita saturar el disco externo con escrituras simultáneas.
      for (const [id, file] of accepted) {
        queue.current = queue.current.then(() => processFile(id, file, target))
      }
    },
    [processFile],
  )

  const importPath = useCallback(
    async (path: string, target: ImportTarget) => {
      const name = path.split('/').pop() ?? path
      const id = nextId()
      setItems((prev) => [
        { id, name, size: 0, status: 'checking', progress: 0, source: 'path' },
        ...prev,
      ])
      try {
        let res = await api.importFromPath({ path, project_id: target.projectId })
        if (!res.job && res.duplicates.length) {
          patch(id, { status: 'confirm' })
          const choice = await askDuplicate(name, res.duplicates)
          if (choice === 'skip') {
            patch(id, { status: 'cancelled', error: 'Omitido: ya estaba importado.' })
            return
          }
          res = await api.importFromPath({
            path,
            project_id: target.projectId,
            allow_duplicate: true,
          })
        }
        patch(id, { status: 'uploading', jobId: res.job?.id, progress: 0 })
        refresh()
      } catch (err) {
        const message = err instanceof ApiError ? err.message : String(err)
        patch(id, { status: 'error', error: message })
        toast.error(`No se pudo importar «${name}»`, { description: message })
      }
    },
    [askDuplicate, patch, refresh],
  )

  const pickWithBrowser = useCallback((target: ImportTarget = {}) => {
    inputTarget.current = target
    inputRef.current?.click()
  }, [])

  const pickAndImport = useCallback(
    async (target: ImportTarget = {}) => {
      if (!system?.native_dialogs) {
        pickWithBrowser(target)
        return
      }
      try {
        const picked = await api.pickFiles()
        if (!picked.supported) {
          pickWithBrowser(target)
          return
        }
        const paths = target.projectId ? picked.paths.slice(0, 1) : picked.paths
        for (const path of paths) await importPath(path, target)
      } catch (err) {
        toast.error('No se pudo abrir el selector', {
          description: err instanceof ApiError ? err.message : String(err),
        })
      }
    },
    [importPath, pickWithBrowser, system?.native_dialogs],
  )

  const cancel = useCallback(
    (id: string) => {
      cancelled.current.add(id)
      const handle = handles.current.get(id)
      if (handle) handle.abort()
      else {
        const item = items.find((it) => it.id === id)
        if (item?.jobId && item.source === 'path') void api.cancelJob(item.jobId).then(refresh)
        patch(id, { status: 'cancelled', error: 'Cancelado.' })
      }
    },
    [items, patch, refresh],
  )

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((it) => it.id !== id))
  }, [])

  const busy = items.some((it) =>
    ['queued', 'checking', 'confirm', 'uploading', 'finalizing'].includes(it.status),
  )

  const value = useMemo(
    () => ({ items, importFiles, pickAndImport, pickWithBrowser, cancel, dismiss, busy }),
    [items, importFiles, pickAndImport, pickWithBrowser, cancel, dismiss, busy],
  )

  return (
    <ImporterContext.Provider value={value}>
      {children}
      <input
        ref={inputRef}
        type="file"
        accept=".mp4,.mov,video/mp4,video/quicktime"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) importFiles(e.target.files, inputTarget.current)
          e.target.value = ''
        }}
      />
      <Dialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) answer('skip')
        }}
        icon={<Copy className="size-5" />}
        title="Este video ya está en tu biblioteca"
        description={
          confirm && (
            <>
              «{confirm.name}» coincide con un video importado anteriormente. Importarlo de nuevo
              ocupará espacio adicional en el disco.
            </>
          )
        }
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => answer('skip')}
            >
              Omitir
            </Button>
            <Button
              variant="primary"
              onClick={() => answer('import')}
            >
              Importar una copia
            </Button>
          </>
        }
      >
        <ul className="space-y-2">
          {confirm?.duplicates.map((d) => (
            <li
              key={d.asset_id}
              className="rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-sm"
            >
              <div className="font-medium text-fg">{d.project_name}</div>
              <div className="text-xs text-fg-faint">
                {d.original_filename} · importado {formatDateTime(d.created_at)}
              </div>
            </li>
          ))}
        </ul>
      </Dialog>
    </ImporterContext.Provider>
  )
}
