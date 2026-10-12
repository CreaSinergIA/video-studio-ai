import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Tabs } from 'radix-ui'
import {
  ArrowLeft,
  BookmarkPlus,
  Check,
  ChevronDown,
  CircleAlert,
  CloudUpload,
  Download,
  Ellipsis,
  FolderSearch,
  Pencil,
  RotateCcw,
  Trash,
  Unplug,
  Upload,
  Wand,
  Sparkles,
} from 'lucide-react'
import { toast } from 'sonner'
import { AnalysisPanel } from '@/components/analysis/AnalysisPanel'
import { ExportDialog } from '@/components/analysis/ExportDialog'
import { TranscriptPanel } from '@/components/analysis/TranscriptPanel'
import { ConfigForm } from '@/components/config/ConfigForm'
import { TrackOverlay } from '@/components/editor/TrackOverlay'
import { useAnalyze } from '@/hooks/useAnalyze'
import { MetadataPanel } from '@/components/editor/MetadataPanel'
import { SubtitleOverlay } from '@/components/editor/SubtitleOverlay'
import { Timeline } from '@/components/editor/Timeline'
import { VideoPlayer } from '@/components/editor/VideoPlayer'
import { usePlayer } from '@/hooks/usePlayer'
import { DeleteDialog } from '@/components/library/ProjectDialogs'
import { DropArea, DropHero } from '@/components/library/DropZone'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge, EmptyState, ProgressBar, Spinner } from '@/components/ui/feedback'
import { Field, Input, Select } from '@/components/ui/fields'
import { Menu } from '@/components/ui/Menu'
import { useImporter } from '@/hooks/importer-context'
import { keys, useAnalysis, useAnimationLayout, useCatalog, useExports, useJobs, useAnimations, usePlan, usePresets, useProject, useSafeZones, useSaveGeneral, useSettings, useSubtitleTrack } from '@/hooks/queries'
import { SafeZoneGuides } from '@/components/editor/SafeZoneGuides'
import { PlanPanel } from '@/components/plan/PlanPanel'
import { SceneDialog } from '@/components/plan/SceneDialog'
import { FlowSteps, type FlowStep } from '@/components/editor/FlowSteps'
import { TYPE_META, fmtT } from '@/lib/plan'
import { ApiError, CLIENT_HEADER, api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatDuration, formatFps, formatResolution, ORIENTATION_LABEL, FILE_MANAGER } from '@/lib/format'
import type { EditConfig, EditorState, ProjectDetail } from '@/lib/types'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === 'idle') return null
  return (
    <span
      className={cn('flex items-center gap-1.5 text-xs', state === 'error' ? 'text-danger' : 'text-fg-faint')}
      aria-live="polite"
    >
      {state === 'saving' && <Spinner className="size-3" />}
      {state === 'saved' && <Check className="size-3.5 text-success" />}
      {state === 'error' && <CircleAlert className="size-3.5" />}
      {state === 'saving' ? 'Guardando…' : state === 'saved' ? 'Guardado' : 'Error al guardar'}
    </span>
  )
}

function InlineName({ project }: { project: ProjectDetail }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(project.name)
  const [syncedName, setSyncedName] = useState(project.name)
  if (syncedName !== project.name) {
    setSyncedName(project.name)
    setValue(project.name)
  }
  const commit = async () => {
    setEditing(false)
    const name = value.trim()
    if (!name || name === project.name) {
      setValue(project.name)
      return
    }
    try {
      const updated = await api.updateProject(project.id, { name })
      qc.setQueryData(keys.project(project.id), updated)
      qc.invalidateQueries({ queryKey: keys.projects, exact: true })
    } catch (err) {
      setValue(project.name)
      toast.error('No se pudo renombrar', { description: err instanceof ApiError ? err.message : String(err) })
    }
  }
  if (editing) {
    return (
      <Input
        autoFocus
        value={value}
        maxLength={200}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void commit()
          if (e.key === 'Escape') {
            setValue(project.name)
            setEditing(false)
          }
        }}
        className="h-8 w-72 text-[15px] font-semibold"
        aria-label="Nombre del proyecto"
      />
    )
  }
  return (
    <div className="group flex min-w-0 items-center gap-1">
      <h1
        className="cursor-text truncate rounded-lg px-1.5 py-1 text-[15px] font-semibold tracking-tight text-fg hover:bg-surface-3"
        onClick={() => setEditing(true)}
        title="Clic para renombrar"
      >
        {project.name}
      </h1>
      <button
        type="button"
        onClick={() => setEditing(true)}
        aria-label={`Renombrar proyecto «${project.name}»`}
        className="grid size-7 shrink-0 place-items-center rounded-md text-fg-faint opacity-0 transition hover:bg-surface-3 hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Pencil className="size-3.5" />
      </button>
    </div>
  )
}

function SavePresetDialog({ open, onOpenChange, config }: { open: boolean; onOpenChange: (o: boolean) => void; config: EditConfig }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setName('')
      setDescription('')
    }
  }
  const submit = async () => {
    setSaving(true)
    try {
      const preset = await api.createPreset({ name: name.trim(), description, config })
      qc.invalidateQueries({ queryKey: keys.presets })
      toast.success(`Preset «${preset.name}» guardado`)
      onOpenChange(false)
    } catch (err) {
      toast.error('No se pudo guardar el preset', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setSaving(false)
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<BookmarkPlus className="size-5" />}
      title="Guardar como preset"
      description="Guarda la configuración actual (estilo, subtítulos, animaciones, audio y exportación) para reutilizarla en otros proyectos."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="primary" disabled={!name.trim()} loading={saving} onClick={submit}>
            Guardar preset
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) void submit()
        }}
      >
        <Field label="Nombre" stacked htmlFor="preset-name">
          <Input id="preset-name" autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} placeholder="Ej. Reels tecnológicos" />
        </Field>
        <Field label="Descripción" stacked htmlFor="preset-desc">
          <Input id="preset-desc" value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} placeholder="Opcional" />
        </Field>
      </form>
    </Dialog>
  )
}

export function EditorPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { data: project, isLoading, isError, error } = useProject(projectId)
  if (isLoading) {
    return (
      <div className="grid h-full place-items-center">
        <Spinner className="size-5 text-fg-faint" />
      </div>
    )
  }
  if (isError || !project) {
    return (
      <EmptyState
        className="h-full"
        icon={<CircleAlert className="size-5" />}
        title="Proyecto no encontrado"
        description={(error as Error | null)?.message ?? 'Puede que se haya eliminado.'}
        action={
          <Button variant="secondary" onClick={() => navigate('/')}>
            Volver a la biblioteca
          </Button>
        }
      />
    )
  }
  return <EditorView key={project.id} project={project} />
}

function EditorView({ project }: { project: ProjectDetail }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: catalog } = useCatalog()
  const { data: presets } = usePresets()
  const { data: settings } = useSettings()
  const saveGeneral = useSaveGeneral()
  const importer = useImporter()
  const prefs = settings?.general

  const [draft, setDraft] = useState<EditConfig | null>(project.config)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [overlay, setOverlay] = useState(false)
  // Guías de zonas seguras: preferencia local del panel (nunca afectan a la exportación).
  const [guides, setGuides] = useState(() => {
    try {
      return localStorage.getItem('vsa.guides') === '1'
    } catch {
      return false
    }
  })
  const toggleGuides = () =>
    setGuides((g) => {
      try {
        localStorage.setItem('vsa.guides', g ? '0' : '1')
      } catch {
        /* sin almacenamiento local: solo esta sesión */
      }
      return !g
    })
  const [showSubs, setShowSubs] = useState(true)
  const [exportOpen, setExportOpen] = useState(false)
  const source = project.source
  const analysis = useAnalysis(project.id, Boolean(source))
  const trackVersion = [
    analysis.data?.transcript?.id,
    analysis.data?.transcript?.updated_at,
    analysis.data?.visual?.id,
    project.updated_at,
  ].join('|')
  const track = useSubtitleTrack(project.id, trackVersion, Boolean(source))
  const analyze = useAnalyze(project.id, source)
  const planState = usePlan(project.id, Boolean(source))
  const animState = useAnimations(project.id, Boolean(planState.data?.plan?.approved_version))
  const animationMap = Object.fromEntries((animState.data?.items ?? []).map((i) => [i.intervention_id, i.status]))
  const [sceneIv, setSceneIv] = useState<string | null>(null)
  const exportsList = useExports(source ? project.id : undefined)
  const approvedV = planState.data?.plan?.approved_version ?? null
  const animItems = (animState.data?.items ?? []).filter((i) => i.status !== 'kept')
  const flow: FlowStep[] = [
    { id: 'import', label: 'Importar', done: Boolean(source), hint: 'Video original del proyecto' },
    { id: 'analyze', label: 'Analizar', done: Boolean(analysis.data?.visual && analysis.data?.transcript), hint: 'Transcripción, escenas y fotogramas (botón «Analizar video»)' },
    { id: 'customize', label: 'Personalizar', done: Boolean(planState.data?.plan), hint: 'Estilo, subtítulos, audio y destino (pestaña Edición)' },
    { id: 'plan', label: 'Planificar', done: Boolean(planState.data?.plan), hint: 'Claude propone el plan de edición (Plan IA)' },
    { id: 'approve', label: 'Aprobar', done: approvedV !== null, hint: 'Revisa y aprueba el plan (Plan IA)' },
    { id: 'generate', label: 'Generar', done: animItems.length > 0 && animItems.every((i) => i.status === 'ready'), hint: 'Genera las animaciones del plan aprobado' },
    { id: 'review', label: 'Revisar', done: animItems.some((i) => i.preview), hint: 'Previsualiza y modifica escenas (línea de tiempo → escena)' },
    {
      id: 'export',
      label: 'Exportar',
      done: (exportsList.data ?? []).some((e) => e.status === 'succeeded' && (e.settings?.animations as { plan_version?: number } | null)?.plan_version === approvedV),
      hint: 'Exporta el video con la versión aprobada actual',
    },
  ]
  const [selectedIv, setSelectedIv] = useState<string | null>(null)
  const { data: jobs } = useJobs()
  const projectJobs = (jobs ?? []).filter((j) => j.project_id === project.id && (j.status === 'queued' || j.status === 'running'))
  const analyzing = projectJobs.some((j) => j.kind === 'transcribe' || j.kind === 'analyze_visual')
  const realignBusy = projectJobs.some((j) => j.kind === 'align_segments')
  const [savePresetOpen, setSavePresetOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [decodeFailed, setDecodeFailed] = useState(false)
  const [requestingProxy, setRequestingProxy] = useState(false)
  const [tab, setTab] = useState<string>(
    ['file', 'transcript', 'analysis', 'plan'].includes(project.editor_state.settings_tab) ? project.editor_state.settings_tab : 'edit',
  )
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const stateTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const opened = useRef<string | null>(null)

  const hasSavedState = Object.keys(project.editor_state).length > 0 && project.editor_state.position !== undefined
  const player = usePlayer({
    volume: hasSavedState ? project.editor_state.volume : (prefs?.default_volume ?? 0.8),
    muted: project.editor_state.muted ?? false,
  })

  // Marca de «abierto recientemente».
  useEffect(() => {
    if (opened.current === project.id) return
    opened.current = project.id
    void api.openProject(project.id).then((p) => qc.setQueryData(keys.project(p.id), p)).catch(() => undefined)
  }, [project.id, qc])

  /** Guarda posición, volumen y pestaña (con rebote salvo `immediate`). */
  const persistState = (patch: Partial<EditorState>, immediate = false) => {
    const { currentTime, duration, volume: vol, muted: mute } = player.state
    // Sin metadatos cargados la posición sería 0: no sobrescribir la guardada.
    const loaded = duration > 0
    if (!loaded && !('settings_tab' in patch)) return
    const body: EditorState = {
      position:
        prefs?.remember_playback_position === false ? 0 : loaded ? currentTime : project.editor_state.position,
      volume: vol,
      muted: mute,
      settings_tab: tab,
      ...patch,
    }
    const send = () =>
      void fetch(`/api/projects/${project.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...CLIENT_HEADER },
        body: JSON.stringify({ editor_state: body }),
        keepalive: true,
      }).catch(() => undefined)
    clearTimeout(stateTimer.current)
    if (immediate) send()
    else stateTimer.current = setTimeout(send, 1200)
  }
  const persistFromEffect = useEffectEvent((immediate: boolean) => persistState({}, immediate))

  // Guardar posición y volumen: al pausar, cada pocos segundos y al salir.
  const { playing, volume, muted } = player.state
  const hasSource = Boolean(project.source)
  useEffect(() => {
    if (!hasSource) return
    persistFromEffect(false)
    if (!playing) return
    const id = setInterval(() => persistFromEffect(true), 5000)
    return () => clearInterval(id)
  }, [playing, volume, muted, hasSource])
  useEffect(() => () => persistFromEffect(true), [])

  const onConfigChange = (next: EditConfig) => {
    setDraft(next)
    setSaveState('saving')
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(async () => {
      try {
        const updated = await api.updateProject(project.id, { config: next })
        qc.setQueryData(keys.project(project.id), updated)
        qc.invalidateQueries({ queryKey: keys.projects, exact: true })
        qc.invalidateQueries({ queryKey: keys.track(project.id) })
        setSaveState('saved')
      } catch (err) {
        setSaveState('error')
        toast.error('No se pudo guardar la configuración', { description: err instanceof ApiError ? err.message : String(err) })
      }
    }, 500)
  }

  const basePreset = presets?.find((p) => p.id === project.preset_id)
  const modified = useMemo(
    () => Boolean(draft && basePreset && JSON.stringify(draft) !== JSON.stringify(basePreset.config)),
    [draft, basePreset],
  )

  const applyPreset = async (presetId: string) => {
    try {
      const updated = await api.applyPreset(project.id, presetId)
      qc.setQueryData(keys.project(project.id), updated)
      setDraft(updated.config)
      setSaveState('saved')
      toast.success(`Preset «${presets?.find((p) => p.id === presetId)?.name}» aplicado`)
    } catch (err) {
      toast.error('No se pudo aplicar el preset', { description: err instanceof ApiError ? err.message : String(err) })
    }
  }

  const asset = project.source
  const job = project.active_job
  const config = draft ?? project.config
  const platform = config.delivery?.platform ?? 'universal'
  const safeZones = useSafeZones()
  const layout = useAnimationLayout(project.id, platform, guides && Boolean(planState.data?.plan?.approved_version))
  const profile = safeZones.data?.find((p) => p.id === platform) ?? null

  const hasTrack = Boolean(track.data && track.data.blocks.length > 0)
  let stage: React.ReactNode
  if (!project.storage_available) {
    stage = (
      <EmptyState
        icon={<Unplug className="size-5" />}
        title="Almacenamiento desconectado"
        description={project.storage_message ?? 'Conecta el disco para reproducir este proyecto. Tus ajustes siguen guardados.'}
      />
    )
  } else if (!asset) {
    stage = job ? (
      <div className="w-full max-w-md text-center">
        <CloudUpload className="mx-auto mb-4 size-8 text-accent" />
        <p className="text-sm font-medium text-fg">{job.stage ?? job.label}</p>
        <ProgressBar value={job.progress} className="mt-4" label="Progreso de importación" />
      </div>
    ) : (
      <div className="w-full max-w-2xl">
        <DropHero
          title="Importa el video de este proyecto"
          subtitle="Arrastra un MP4 o MOV aquí. Se guardará una copia en el almacenamiento; el original no se modifica."
          onBrowse={() => void importer.pickAndImport({ projectId: project.id })}
          actions={
            <Button variant="primary" icon={<Upload className="size-4" />} onClick={() => void importer.pickAndImport({ projectId: project.id })}>
              Elegir video
            </Button>
          }
        />
      </div>
    )
  } else if (asset.playback === 'unavailable') {
    stage = (
      <div className="relative w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-surface-1 text-center">
        {asset.thumbnail_url && <img src={asset.thumbnail_url} alt="" className="max-h-72 w-full object-contain opacity-60" />}
        <div className="p-6">
          {job ? (
            <>
              <p className="text-sm font-medium text-fg">{job.stage ?? job.label}</p>
              <ProgressBar value={job.progress} className="mt-3" label="Progreso" />
            </>
          ) : (
            <>
              <p className="text-sm text-fg-muted">
                El códec de este video ({asset.video_codec}) no se reproduce en el navegador. Crea un proxy H.264 de
                previsualización; el original se conserva intacto para la exportación.
              </p>
              <Button className="mt-4" variant="primary" icon={<Wand className="size-4" />} onClick={() =>
                  void api
                    .requestProxy(asset.id)
                    .then(() => qc.invalidateQueries({ queryKey: keys.project(project.id) }))
                    .catch((err) =>
                      toast.error('No se pudo crear el proxy', { description: err instanceof ApiError ? err.message : String(err) }),
                    )
                }>
                Crear proxy de reproducción
              </Button>
            </>
          )}
        </div>
      </div>
    )
  } else {
    // Si el navegador no pudo decodificar el original y ya hay proxy, usarlo.
    const useProxy = decodeFailed && asset.proxy_ready && asset.playback === 'original'
    const proxyJob = job?.kind === 'proxy' ? job : null
    stage = (
      <VideoPlayer
        player={player}
        src={useProxy ? `/api/media/${asset.id}/proxy` : (asset.stream_url as string)}
        decodeAction={
          proxyJob ? (
            <div className="mx-auto w-56 text-xs text-white/80">
              {proxyJob.stage ?? proxyJob.label} · {Math.round(proxyJob.progress * 100)} %
              <ProgressBar value={proxyJob.progress} className="mt-2" label="Progreso del proxy" />
            </div>
          ) : (
            <Button
              variant="primary"
              loading={requestingProxy}
              icon={<Wand className="size-4" />}
              onClick={async () => {
                setRequestingProxy(true)
                try {
                  await api.requestProxy(asset.id)
                  await qc.invalidateQueries({ queryKey: keys.project(project.id) })
                } catch (err) {
                  toast.error('No se pudo crear el proxy', { description: err instanceof ApiError ? err.message : String(err) })
                } finally {
                  setRequestingProxy(false)
                }
              }}
            >
              Crear proxy de reproducción
            </Button>
          )
        }
        poster={asset.thumbnail_url}
        width={asset.display_width}
        height={asset.display_height}
        fps={asset.fps}
        loop={prefs?.loop_playback ?? false}
        autoPlay={prefs?.autoplay_on_open ?? false}
        initialPosition={prefs?.remember_playback_position === false ? 0 : project.editor_state.position}
        overlayEnabled={hasTrack ? showSubs : overlay}
        onToggleOverlay={() => (hasTrack ? setShowSubs((v) => !v) : setOverlay((o) => !o))}
        overlayLabel={hasTrack ? 'subtítulos' : 'muestra de estilo de subtítulos'}
        guidesEnabled={guides}
        onToggleGuides={toggleGuides}
        guides={<SafeZoneGuides profile={profile} layout={layout.data ?? null} time={player.state.currentTime} vertical={asset.display_height > asset.display_width * 1.1} />}
        overlay={
          hasTrack && track.data ? (
            <TrackOverlay track={track.data} time={player.state.currentTime} />
          ) : (
            <SubtitleOverlay settings={config.subtitles} orientation={asset.orientation} />
          )
        }
        onLoopChange={(loop) => prefs && saveGeneral.mutate({ ...prefs, loop_playback: loop })}
        onError={(kind) => kind === 'decode' && setDecodeFailed(true)}
      />
    )
  }

  return (
    <DropArea
      className="h-full"
      disabled={Boolean(asset) || !project.storage_available}
      onFiles={(files) => importer.importFiles(files.slice(0, 1), { projectId: project.id })}
      label="Suelta para importar en este proyecto"
    >
      <div className="flex h-full flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface-1/70 px-4 backdrop-blur">
          <Link to="/" className="grid size-8 place-items-center rounded-lg text-fg-muted transition hover:bg-surface-3 hover:text-fg" aria-label="Volver a la biblioteca">
            <ArrowLeft className="size-4" />
          </Link>
          <InlineName project={project} />
          {asset && (
            <div className="hidden items-center gap-1.5 text-xs text-fg-faint lg:flex">
              <Badge>{ORIENTATION_LABEL[asset.orientation]}</Badge>
              <Badge>{formatResolution(asset)}</Badge>
              <Badge>{formatFps(asset.fps)}</Badge>
              <Badge>{formatDuration(asset.duration)}</Badge>
            </div>
          )}
          {job && (
            <Badge tone="accent" icon={<Spinner className="size-3" />}>
              {job.stage ?? job.label} · {Math.round(job.progress * 100)} %
            </Badge>
          )}
          <div className="ml-auto flex items-center gap-3">
            <SaveIndicator state={saveState} />
            {asset && project.storage_available && (
              <div className="flex">
                <Button
                  size="sm"
                  variant="secondary"
                  className="rounded-r-none"
                  loading={analyzing || analyze.busy}
                  icon={<Wand className="size-3.5" />}
                  onClick={() => analyze.start('all')}
                >
                  {analyzing ? 'Analizando…' : 'Analizar video'}
                </Button>
                <Menu
                  items={[
                    { label: 'Solo transcripción', onSelect: () => analyze.start('transcript') },
                    { label: 'Solo escenas y fotogramas', onSelect: () => analyze.start('visual') },
                  ]}
                  trigger={
                    <Button size="icon-sm" variant="secondary" className="w-7 rounded-l-none border-l-0" aria-label="Más opciones de análisis">
                      <ChevronDown className="size-3.5" />
                    </Button>
                  }
                />
              </div>
            )}
            {asset && project.storage_available && (
              <Button
                size="sm"
                variant="secondary"
                icon={<Sparkles className="size-3.5" />}
                loading={Boolean(planState.data?.job)}
                onClick={() => {
                  setTab('plan')
                  persistState({ settings_tab: 'plan' })
                }}
              >
                {planState.data?.job ? 'Planificando…' : planState.data?.plan ? 'Plan IA' : 'Planificar con IA'}
              </Button>
            )}
            {asset && project.storage_available && (
              <Button size="sm" variant="primary" icon={<Download className="size-3.5" />} onClick={() => setExportOpen(true)}>
                Exportar
              </Button>
            )}
            <Menu
              items={[
                { label: 'Guardar configuración como preset…', icon: <BookmarkPlus />, onSelect: () => setSavePresetOpen(true) },
                {
                  label: `Mostrar en ${FILE_MANAGER}`,
                  icon: <FolderSearch />,
                  disabled: !asset || !project.storage_available,
                  onSelect: () => asset && void api.reveal(asset.id),
                },
                {
                  label: project.storage_available ? 'Eliminar proyecto…' : 'Quitar de la biblioteca…',
                  icon: <Trash />,
                  danger: true,
                  separatorBefore: true,
                  onSelect: () => setDeleteOpen(true),
                },
              ]}
              trigger={
                <Button size="icon-sm" variant="ghost" aria-label="Más acciones">
                  <Ellipsis className="size-4" />
                </Button>
              }
            />
          </div>
        </header>
        {asset && project.storage_available && (
          <div className="flex h-9 shrink-0 items-center border-b border-line bg-surface-1/50 px-4">
            <FlowSteps
              steps={flow}
              onSelect={(id) => {
                if (id === 'export') setExportOpen(true)
                else if (id === 'analyze') {
                  setTab('transcript')
                  persistState({ settings_tab: 'transcript' })
                } else if (id === 'customize') {
                  setTab('edit')
                  persistState({ settings_tab: 'edit' })
                } else if (id !== 'import') {
                  setTab('plan')
                  persistState({ settings_tab: 'plan' })
                }
              }}
            />
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="checker relative grid min-h-0 flex-1 place-items-center p-6">{stage}</div>
            {(() => {
                // Barra de la escena seleccionada en la línea de tiempo (plan aprobado).
                const it = animState.data?.items.find((i) => i.intervention_id === selectedIv)
                if (!it || it.status === 'kept') return null
                const label = { pending: 'pendiente', rendering: 'generando', ready: 'disponible', failed: 'con error', kept: '' }[it.status]
                return (
                  <div
                    role="region"
                    aria-label="Escena seleccionada"
                    className="flex shrink-0 items-center gap-2 border-t border-line bg-surface-1 px-4 py-1.5 text-xs"
                  >
                    <span className="font-semibold text-fg-muted">Escena</span>
                    <span className="font-mono text-fg">
                      {fmtT(it.start)}–{fmtT(it.end)}
                    </span>
                    <span style={{ color: TYPE_META[it.type].color }}>{TYPE_META[it.type].short}</span>
                    <span className={it.status === 'failed' ? 'text-danger' : 'text-fg-muted'}>· {label}</span>
                    <Button size="sm" variant="ghost" className="ml-auto h-6 px-2 text-[11px]" onClick={() => player.seek(it.start)}>
                      Ir al inicio
                    </Button>
                    <Button size="sm" variant="secondary" className="h-6 px-2 text-[11px]" onClick={() => setSceneIv(it.intervention_id)}>
                      Abrir escena
                    </Button>
                  </div>
                )
              })()}
            {asset && project.storage_available && (
              <Timeline
                asset={asset}
                currentTime={player.state.currentTime}
                onSeek={player.seek}
                scenes={analysis.data?.visual?.scenes}
                speech={analysis.data?.transcript?.stats.voice?.speech}
                plan={planState.data?.plan?.document.interventions}
                selectedPlan={selectedIv}
                animation={animationMap}
                onSelectPlan={(i) => {
                  setSelectedIv(i.id)
                  player.seek(i.start)
                  setTab('plan')
                  persistState({ settings_tab: 'plan' })
                  requestAnimationFrame(() => document.getElementById(`iv-${i.id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
                }}
              />
            )}
          </div>

          <aside className="flex w-[392px] shrink-0 flex-col border-l border-line bg-surface-1">
            <Tabs.Root
              value={tab}
              onValueChange={(v) => {
                setTab(v)
                persistState({ settings_tab: v })
              }}
              className="flex min-h-0 flex-1 flex-col"
            >
              <Tabs.List className="flex shrink-0 gap-0.5 border-b border-line px-2 pt-2" aria-label="Panel del proyecto">
                {[
                  { value: 'edit', label: 'Edición' },
                  { value: 'transcript', label: 'Transcripción' },
                  { value: 'analysis', label: 'Análisis' },
                  { value: 'plan', label: 'Plan IA' },
                  { value: 'file', label: 'Archivo' },
                ].map((t) => (
                  <Tabs.Trigger
                    key={t.value}
                    value={t.value}
                    className="relative whitespace-nowrap px-2 pb-2.5 pt-1.5 text-[13px] font-medium text-fg-faint transition hover:text-fg-muted data-[state=active]:text-fg data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:-bottom-px data-[state=active]:after:h-0.5 data-[state=active]:after:rounded-full data-[state=active]:after:bg-accent"
                  >
                    {t.label}
                  </Tabs.Trigger>
                ))}
              </Tabs.List>
              <Tabs.Content value="edit" className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
                <div className="border-b border-line px-5 py-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-fg-faint">Preset</span>
                    {modified && (
                      <Badge tone="warning" className="h-5">
                        Modificado
                      </Badge>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Select
                      label="Preset"
                      className="min-w-0 flex-1"
                      value={project.preset_id ?? ''}
                      options={[
                        ...(project.preset_id ? [] : [{ value: '', label: 'Sin preset', disabled: true }]),
                        ...(presets ?? []).map((p) => ({ value: p.id, label: p.name })),
                      ]}
                      onValueChange={(v) => v && void applyPreset(v)}
                    />
                    {modified && basePreset && (
                      <Button size="icon" variant="secondary" aria-label="Restablecer valores del preset" title="Restablecer valores del preset" onClick={() => void applyPreset(basePreset.id)}>
                        <RotateCcw className="size-4" />
                      </Button>
                    )}
                    <Button size="icon" variant="secondary" aria-label="Guardar como preset" title="Guardar como preset" onClick={() => setSavePresetOpen(true)}>
                      <BookmarkPlus className="size-4" />
                    </Button>
                  </div>
                </div>
                {catalog && draft ? (
                  <ConfigForm config={draft} onChange={onConfigChange} catalog={catalog} asset={asset} subtitleSafeArea={track.data?.safe_area ?? null} />
                ) : (
                  <div className="space-y-3 p-5">
                    {Array.from({ length: 5 }, (_, i) => (
                      <div key={i} className="skeleton h-12 rounded-xl" />
                    ))}
                  </div>
                )}
              </Tabs.Content>
              <Tabs.Content value="transcript" className="min-h-0 flex-1 overflow-hidden focus:outline-none">
                {asset ? (
                  <TranscriptPanel
                    projectId={project.id}
                    state={analysis.data}
                    currentTime={player.state.currentTime}
                    onSeek={player.seek}
                    realignBusy={realignBusy}
                    onAnalyze={() => analyze.start('all')}
                    analyzing={analyzing}
                  />
                ) : (
                  <EmptyState icon={<Upload className="size-5" />} title="Sin video" description="Importa un video para transcribirlo." />
                )}
              </Tabs.Content>
              <Tabs.Content value="analysis" className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
                {asset ? (
                  <AnalysisPanel
                    projectId={project.id}
                    state={analysis.data}
                    currentTime={player.state.currentTime}
                    onSeek={player.seek}
                    onAnalyze={() => analyze.start('all')}
                    analyzing={analyzing}
                  />
                ) : (
                  <EmptyState icon={<Upload className="size-5" />} title="Sin video" description="Importa un video para analizarlo." />
                )}
              </Tabs.Content>
              <Tabs.Content value="plan" className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
                {asset ? (
                  <PlanPanel
                    projectId={project.id}
                    asset={asset}
                    state={planState.data}
                    styleId={config.style.id}
                    analyzed={Boolean(analysis.data?.visual)}
                    selected={selectedIv}
                    onSelect={setSelectedIv}
                    onSeek={player.seek}
                    onOpenScene={setSceneIv}
                  />
                ) : (
                  <EmptyState icon={<Upload className="size-5" />} title="Sin video" description="Importa un video para planificar su edición." />
                )}
              </Tabs.Content>
              <Tabs.Content value="file" className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
                {asset ? (
                  <MetadataPanel project={project} asset={asset} />
                ) : (
                  <EmptyState icon={<Upload className="size-5" />} title="Sin video" description="Importa un video para ver sus metadatos." />
                )}
              </Tabs.Content>
            </Tabs.Root>
          </aside>
        </div>
      </div>
      {draft && <SavePresetDialog open={savePresetOpen} onOpenChange={setSavePresetOpen} config={draft} />}
      {analyze.dialog}
      {sceneIv && (
        <SceneDialog
          projectId={project.id}
          iid={sceneIv}
          onClose={() => setSceneIv(null)}
          onExport={() => {
            setSceneIv(null)
            setExportOpen(true)
          }}
        />
      )}
      {asset && (
        <ExportDialog open={exportOpen} onOpenChange={setExportOpen} projectId={project.id} asset={asset} initial={config.export} />
      )}
      <DeleteDialog project={deleteOpen ? project : null} onOpenChange={setDeleteOpen} onDeleted={() => navigate('/')} />
    </DropArea>
  )
}
