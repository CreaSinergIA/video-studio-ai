import { useMemo, useState } from 'react'
import { ChevronDown, FolderPlus, LayoutGrid, List, MonitorUp, Search, Sparkles, Upload } from 'lucide-react'
import { DeleteDialog, NewProjectDialog, RenameDialog } from '@/components/library/ProjectDialogs'
import { ProjectCard, ProjectRow, type CardActions } from '@/components/library/ProjectCard'
import { DropArea, DropHero } from '@/components/library/DropZone'
import { StoragePicker } from '@/components/settings/StoragePicker'
import { Button } from '@/components/ui/Button'
import { EmptyState, Spinner } from '@/components/ui/feedback'
import { Input, Segmented, Select } from '@/components/ui/fields'
import { Menu } from '@/components/ui/Menu'
import { useImporter } from '@/hooks/importer-context'
import { useProjects, useSaveGeneral, useSettings, useStorageStatus, useSystemInfo } from '@/hooks/queries'
import type { GeneralPreferences, ProjectSummary } from '@/lib/types'
import { FILE_MANAGER } from '@/lib/format'

function Welcome() {
  return (
    <div className="h-full overflow-y-auto bg-glow">
      <div className="mx-auto max-w-3xl px-8 py-16 animate-rise">
        <div className="mb-10">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-fg-muted">
            <Sparkles className="size-3.5 text-accent" />
            Edición asistida por IA, en local
          </div>
          <h1 className="text-4xl font-semibold tracking-tight text-fg">Bienvenido a Video Studio AI</h1>
          <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-fg-muted">
            Antes de importar videos, elige dónde guardarlos. Recomendamos una carpeta dedicada en
            tu disco externo: allí vivirán las copias de tus videos, miniaturas, transcripciones,
            planes de edición y exportaciones.
          </p>
        </div>
        <div className="rounded-2xl border border-line bg-surface-1 p-6 shadow-panel">
          <h2 className="mb-4 text-[15px] font-semibold text-fg">Carpeta de almacenamiento</h2>
          <StoragePicker submitLabel="Empezar" />
        </div>
      </div>
    </div>
  )
}

const SORTS: { value: GeneralPreferences['library_sort']; label: string }[] = [
  { value: 'recent', label: 'Abiertos recientemente' },
  { value: 'created', label: 'Fecha de creación' },
  { value: 'name', label: 'Nombre' },
  { value: 'duration', label: 'Duración' },
]

function sortProjects(list: ProjectSummary[], sort: GeneralPreferences['library_sort']) {
  const copy = [...list]
  const time = (iso: string | null) => (iso ? new Date(iso).getTime() : 0)
  switch (sort) {
    case 'name':
      return copy.sort((a, b) => a.name.localeCompare(b.name, 'es', { sensitivity: 'base' }))
    case 'duration':
      return copy.sort((a, b) => (b.source?.duration ?? 0) - (a.source?.duration ?? 0))
    case 'created':
      return copy.sort((a, b) => time(b.created_at) - time(a.created_at))
    default:
      return copy.sort(
        (a, b) => time(b.last_opened_at ?? b.created_at) - time(a.last_opened_at ?? a.created_at),
      )
  }
}

export function LibraryPage() {
  const storage = useStorageStatus()
  const { data: projects, isLoading, isError, error } = useProjects()
  const { data: settings } = useSettings()
  const { data: system } = useSystemInfo()
  const saveGeneral = useSaveGeneral()
  const importer = useImporter()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<ProjectSummary | null>(null)
  const [deleting, setDeleting] = useState<ProjectSummary | null>(null)

  const prefs = settings?.general
  const view = prefs?.library_view ?? 'grid'
  const sort = prefs?.library_sort ?? 'recent'
  const setPref = (patch: Partial<GeneralPreferences>) => prefs && saveGeneral.mutate({ ...prefs, ...patch })

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase()
    const filtered = (projects ?? []).filter(
      (p) =>
        !term ||
        p.name.toLowerCase().includes(term) ||
        p.source?.original_filename.toLowerCase().includes(term),
    )
    return sortProjects(filtered, sort)
  }, [projects, query, sort])

  const actions: CardActions = { onRename: setRenaming, onDelete: setDeleting }
  const canImport = Boolean(storage.data?.available)

  if (storage.isLoading) {
    return (
      <div className="grid h-full place-items-center text-fg-faint">
        <Spinner className="size-5" />
      </div>
    )
  }
  if (storage.data && !storage.data.configured) return <Welcome />

  const importButton = (
    <div className="flex">
      <Button
        variant="primary"
        icon={<Upload className="size-4" />}
        disabled={!canImport}
        onClick={() => void importer.pickAndImport()}
        className={system?.native_dialogs ? 'rounded-r-none' : undefined}
      >
        Importar video
      </Button>
      {system?.native_dialogs && (
        <Menu
          items={[
            { label: `Elegir en ${FILE_MANAGER} (recomendado)`, icon: <Upload />, onSelect: () => void importer.pickAndImport() },
            { label: 'Subir desde el navegador', icon: <MonitorUp />, onSelect: () => importer.pickWithBrowser() },
          ]}
          trigger={
            <Button
              variant="primary"
              size="icon"
              disabled={!canImport}
              aria-label="Más opciones de importación"
              className="w-8 rounded-l-none border-l border-black/15"
            >
              <ChevronDown className="size-4" />
            </Button>
          }
        />
      )}
    </div>
  )

  return (
    <DropArea onFiles={(files) => importer.importFiles(files)} disabled={!canImport} className="h-full">
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-[1480px] px-8 pb-24 pt-8">
          <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-[26px] font-semibold tracking-tight text-fg">Biblioteca</h1>
              <p className="mt-1 text-sm text-fg-muted">
                {projects?.length
                  ? `${projects.length} proyecto${projects.length === 1 ? '' : 's'} · arrastra videos en cualquier lugar para importarlos`
                  : 'Tus proyectos de video aparecerán aquí'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {Boolean(projects?.length) && (
                <>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-faint" />
                    <Input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Buscar proyectos"
                      className="w-56 pl-9"
                      aria-label="Buscar proyectos"
                    />
                  </div>
                  <Select label="Ordenar" value={sort} onValueChange={(v) => setPref({ library_sort: v })} options={SORTS} className="min-w-48" />
                  <Segmented
                    label="Vista"
                    value={view}
                    onValueChange={(v) => setPref({ library_view: v })}
                    options={[
                      { value: 'grid', label: '', icon: <LayoutGrid className="size-4" />, hint: 'Cuadrícula' },
                      { value: 'list', label: '', icon: <List className="size-4" />, hint: 'Lista' },
                    ]}
                  />
                </>
              )}
              <Button variant="secondary" icon={<FolderPlus className="size-4" />} disabled={!canImport} onClick={() => setCreating(true)}>
                Nuevo proyecto
              </Button>
              {importButton}
            </div>
          </header>

          {isLoading ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-5">
              {Array.from({ length: 6 }, (_, i) => (
                <div key={i} className="overflow-hidden rounded-2xl border border-line bg-surface-1">
                  <div className="skeleton aspect-[16/10]" />
                  <div className="space-y-2 p-4">
                    <div className="skeleton h-4 w-2/3 rounded" />
                    <div className="skeleton h-3 w-1/2 rounded" />
                  </div>
                </div>
              ))}
            </div>
          ) : isError ? (
            <EmptyState icon={<Search className="size-5" />} title="No se pudo cargar la biblioteca" description={(error as Error).message} />
          ) : !projects?.length ? (
            <DropHero
              onBrowse={() => canImport && void importer.pickAndImport()}
              actions={
                <>
                  {importButton}
                  <Button variant="ghost" icon={<FolderPlus className="size-4" />} disabled={!canImport} onClick={() => setCreating(true)}>
                    Crear proyecto vacío
                  </Button>
                </>
              }
            />
          ) : visible.length === 0 ? (
            <EmptyState icon={<Search className="size-5" />} title="Sin resultados" description={`Ningún proyecto coincide con «${query}».`} />
          ) : view === 'grid' ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-5">
              {visible.map((p) => (
                <ProjectCard key={p.id} project={p} actions={actions} />
              ))}
            </div>
          ) : (
            <div role="table" aria-label="Proyectos" className="rounded-2xl border border-line bg-surface-1 p-2">
              <div
                role="row"
                className="grid grid-cols-[88px_minmax(0,2.2fr)_1fr_0.8fr_0.9fr_1fr_44px] gap-4 px-3 pb-2 pt-1 text-[11px] font-medium uppercase tracking-wide text-fg-faint"
              >
                <span />
                <span>Nombre</span>
                <span>Resolución</span>
                <span>Orientación</span>
                <span>Duración</span>
                <span>Estado</span>
                <span />
              </div>
              {visible.map((p) => (
                <ProjectRow key={p.id} project={p} actions={actions} />
              ))}
            </div>
          )}
        </div>
      </div>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
      <RenameDialog project={renaming} onOpenChange={(o) => !o && setRenaming(null)} />
      <DeleteDialog project={deleting} onOpenChange={(o) => !o && setDeleting(null)} />
    </DropArea>
  )
}
