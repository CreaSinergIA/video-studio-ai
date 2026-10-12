import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { FolderPlus, Pencil, Trash } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Field, Input, Select } from '@/components/ui/fields'
import { keys, usePresets } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import type { ProjectSummary } from '@/lib/types'

export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data: presets } = usePresets()
  const [name, setName] = useState('')
  const [presetId, setPresetId] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setName('')
      setPresetId('')
    }
  }
  const selectedPreset = presetId || presets?.find((p) => p.is_default)?.id || presets?.[0]?.id || ''

  const submit = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      const project = await api.createProject(name.trim(), selectedPreset || null)
      qc.invalidateQueries({ queryKey: keys.projects })
      onOpenChange(false)
      navigate(`/projects/${project.id}`)
    } catch (err) {
      toast.error('No se pudo crear el proyecto', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<FolderPlus className="size-5" />}
      title="Nuevo proyecto"
      description="Crea un proyecto vacío e importa su video después, o arrastra un video a la biblioteca para crearlo directamente."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="primary" loading={saving} disabled={!name.trim()} onClick={submit}>
            Crear proyecto
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
        className="space-y-1"
      >
        <Field label="Nombre" stacked htmlFor="new-project-name">
          <Input
            id="new-project-name"
            autoFocus
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej. Lanzamiento de producto"
          />
        </Field>
        {presets && presets.length > 0 && (
          <Field label="Preset inicial" hint="Define estilo, subtítulos, animación y exportación." stacked>
            <Select
              label="Preset inicial"
              value={selectedPreset}
              onValueChange={setPresetId}
              className="w-full"
              options={presets.map((p) => ({ value: p.id, label: p.is_default ? `${p.name} (predeterminado)` : p.name }))}
            />
          </Field>
        )}
      </form>
    </Dialog>
  )
}

export function RenameDialog({
  project,
  onOpenChange,
}: {
  project: ProjectSummary | null
  onOpenChange: (o: boolean) => void
}) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [forProject, setForProject] = useState(project)
  if (project !== forProject) {
    setForProject(project)
    if (project) setName(project.name)
  }

  const submit = async () => {
    if (!project || !name.trim()) return
    setSaving(true)
    try {
      const updated = await api.updateProject(project.id, { name: name.trim() })
      qc.setQueryData(keys.project(project.id), updated)
      qc.invalidateQueries({ queryKey: keys.projects })
      onOpenChange(false)
    } catch (err) {
      toast.error('No se pudo renombrar', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={project !== null}
      onOpenChange={onOpenChange}
      icon={<Pencil className="size-5" />}
      title="Renombrar proyecto"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="primary" loading={saving} disabled={!name.trim() || name.trim() === project?.name} onClick={submit}>
            Guardar
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <Input autoFocus value={name} maxLength={200} onChange={(e) => setName(e.target.value)} aria-label="Nombre del proyecto" />
      </form>
    </Dialog>
  )
}

export function DeleteDialog({
  project,
  onOpenChange,
  onDeleted,
}: {
  project: ProjectSummary | null
  onOpenChange: (o: boolean) => void
  onDeleted?: () => void
}) {
  const qc = useQueryClient()
  const [confirmed, setConfirmed] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [forProject, setForProject] = useState(project)
  if (project !== forProject) {
    setForProject(project)
    setConfirmed(false)
  }
  const offline = project ? !project.storage_available : false

  const submit = async () => {
    if (!project) return
    setDeleting(true)
    try {
      const res = await api.deleteProject(project.id, offline)
      qc.removeQueries({ queryKey: keys.project(project.id) })
      qc.invalidateQueries({ queryKey: keys.projects })
      toast.success(res.message)
      onOpenChange(false)
      onDeleted?.()
    } catch (err) {
      toast.error('No se pudo eliminar', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <Dialog
      open={project !== null}
      onOpenChange={onOpenChange}
      tone="danger"
      icon={<Trash className="size-5" />}
      title={offline ? 'Quitar de la biblioteca' : 'Eliminar proyecto'}
      description={
        project &&
        (offline ? (
          <>
            El almacenamiento de «{project.name}» no está conectado, así que sus archivos no se
            pueden borrar ahora. Puedes quitarlo de la biblioteca: los archivos quedarán intactos
            en el disco y se recuperarán si vuelves a configurar esa carpeta.
          </>
        ) : (
          <>
            Se eliminará «{project.name}» y su carpeta en el almacenamiento: la copia importada
            del video{project.source ? ` (${formatBytes(project.source.size_bytes)})` : ''},
            miniaturas y ajustes. Tu archivo original fuera de Video Studio no se toca. Esta
            acción no se puede deshacer.
          </>
        ))
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="danger" loading={deleting} disabled={!confirmed} onClick={submit}>
            {offline ? 'Quitar de la biblioteca' : 'Eliminar definitivamente'}
          </Button>
        </>
      }
    >
      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-surface-2 p-3.5 text-sm text-fg">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          className="mt-0.5 size-4 accent-[var(--danger)]"
        />
        <span>
          {offline
            ? 'Entiendo que el proyecto desaparecerá de la biblioteca.'
            : 'Entiendo que se borrarán los archivos de este proyecto.'}
        </span>
      </label>
    </Dialog>
  )
}
