import { useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  CircleCheck,
  Copy,
  Ellipsis,
  HardDrive,
  Pencil,
  Plus,
  Star,
  Trash,
  Unplug,
} from 'lucide-react'
import { toast } from 'sonner'
import { ConfigForm } from '@/components/config/ConfigForm'
import { StylePreview } from '@/components/editor/StylePreview'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge, FutureBadge, ProgressBar, Section, Spinner } from '@/components/ui/feedback'
import { Field, Input, Segmented, Select, Slider, Switch } from '@/components/ui/fields'
import { Menu } from '@/components/ui/Menu'
import {
  keys,
  useCatalog,
  usePresets,
  useAnalysisSettings,
  useAsrModels,
  useSaveGeneral,
  useSettings,
  useStorageLocations,
  useStorageStatus,
  useSystemInfo,
} from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatBytes, formatRelative, STYLE_META } from '@/lib/format'
import type { AnalysisPreferences, EditConfig, GeneralPreferences, Preset, StyleId } from '@/lib/types'
import { StoragePicker } from './StoragePicker'

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

// ---------------------------------------------------------------------------
// Almacenamiento
// ---------------------------------------------------------------------------

export function StorageSection() {
  const { data: status } = useStorageStatus()
  const { data: locations } = useStorageLocations()
  const [changing, setChanging] = useState(false)
  const usage =
    status?.total_bytes && status.free_bytes !== null ? 1 - status.free_bytes / status.total_bytes : null

  return (
    <Section
      title="Almacenamiento"
      description="Carpeta donde se guardan los videos importados y todos sus derivados. Los proyectos y ajustes viven en la base de datos local."
      actions={
        status?.configured && (
          <Button variant="secondary" size="sm" icon={<HardDrive className="size-3.5" />} onClick={() => setChanging(true)}>
            Cambiar ubicación
          </Button>
        )
      }
    >
      {!status ? (
        <Spinner />
      ) : !status.configured ? (
        <StoragePicker />
      ) : (
        <div className="space-y-4">
          <div className="flex items-start gap-4 rounded-xl border border-line bg-surface-2 p-4">
            <div
              className={cn(
                'grid size-11 shrink-0 place-items-center rounded-xl',
                status.available ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
              )}
            >
              {status.available ? <HardDrive className="size-5" /> : <Unplug className="size-5" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-fg">
                  {status.volume_name ? `Disco «${status.volume_name}»` : 'Disco del sistema'}
                </span>
                {status.available ? (
                  <Badge tone="success" icon={<CircleCheck className="size-3" />}>
                    Conectado
                  </Badge>
                ) : (
                  <Badge tone="warning">No disponible</Badge>
                )}
                {status.is_external && <Badge>Externo</Badge>}
              </div>
              <p className="mt-1 truncate font-mono text-xs text-fg-muted" title={status.path ?? ''}>
                {status.path}
              </p>
              {!status.available && <p className="mt-2 text-sm text-warning">{status.message}</p>}
              {usage !== null && (
                <div className="mt-3">
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-4">
                    <div
                      className={cn('h-full rounded-full', usage > 0.9 ? 'bg-danger' : usage > 0.75 ? 'bg-warning' : 'bg-accent')}
                      style={{ width: `${usage * 100}%` }}
                    />
                  </div>
                  <p className="mt-1.5 text-xs tabular text-fg-faint">
                    {formatBytes(status.free_bytes)} libres de {formatBytes(status.total_bytes)}
                  </p>
                </div>
              )}
            </div>
          </div>
          <div className="rounded-xl border border-line px-4 py-3 text-xs leading-relaxed text-fg-muted">
            <p className="mb-1 font-medium text-fg">Estructura</p>
            <code className="font-mono text-[11.5px] text-fg-muted">
              projects/&lt;proyecto&gt;/ originals · frames · analysis · transcripts · animations · previews · exports — cache/uploads
            </code>
            <p className="mt-1.5">
              Cada proyecto incluye un <code className="font-mono">project.json</code>: si reinstalas la app o
              conectas el disco en otro equipo, los proyectos se recuperan al elegir esta carpeta.
            </p>
          </div>
          {locations && locations.length > 1 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-faint">Ubicaciones registradas</h3>
              <ul className="divide-y divide-line rounded-xl border border-line">
                {locations.map((loc) => (
                  <li key={loc.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <span className={cn('size-2 shrink-0 rounded-full', loc.available ? 'bg-success' : 'bg-fg-faint')} />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg">{loc.path}</span>
                    <span className="shrink-0 text-xs text-fg-faint">{loc.project_count} proyecto(s)</span>
                    {loc.active ? <Badge tone="accent">Activa</Badge> : <span className="text-xs text-fg-faint">{loc.last_seen_at ? formatRelative(loc.last_seen_at) : ''}</span>}
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 text-xs text-fg-faint">Los proyectos siguen en su almacenamiento original; los nuevos se crean en la ubicación activa.</p>
            </div>
          )}
        </div>
      )}
      <Dialog
        open={changing}
        onOpenChange={setChanging}
        size="lg"
        icon={<HardDrive className="size-5" />}
        title="Cambiar almacenamiento"
        description="Los proyectos existentes permanecen en su ubicación actual. Los nuevos proyectos se guardarán en la carpeta elegida."
      >
        <div className="pb-3">
          <StoragePicker initialPath={status?.path} onConfigured={() => setChanging(false)} submitLabel="Usar esta carpeta" />
        </div>
      </Dialog>
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Preferencias generales
// ---------------------------------------------------------------------------

export function GeneralSection() {
  const { data } = useSettings()
  const save = useSaveGeneral()
  const prefs = data?.general
  if (!prefs) return <Section title="Preferencias generales"><Spinner /></Section>
  const set = (patch: Partial<GeneralPreferences>) =>
    save.mutate({ ...prefs, ...patch }, { onError: (err) => toast.error('No se pudo guardar', { description: errorText(err) }) })

  return (
    <Section title="Preferencias generales" description="Se guardan automáticamente.">
      <div className="divide-y divide-line">
        <Field label="Tema" hint="Oscuro es el predeterminado del estudio">
          <Segmented
            label="Tema"
            value={prefs.theme}
            onValueChange={(v) => set({ theme: v })}
            options={[
              { value: 'dark', label: 'Oscuro' },
              { value: 'light', label: 'Claro' },
              { value: 'system', label: 'Sistema' },
            ]}
          />
        </Field>
        <Field label="Movimiento reducido" hint="Minimiza las animaciones de la interfaz">
          <Segmented
            label="Movimiento reducido"
            value={prefs.reduce_motion}
            onValueChange={(v) => set({ reduce_motion: v })}
            options={[
              { value: 'system', label: 'Sistema' },
              { value: 'on', label: 'Sí' },
              { value: 'off', label: 'No' },
            ]}
          />
        </Field>
        <Field label="Vista de la biblioteca">
          <Segmented
            label="Vista de la biblioteca"
            value={prefs.library_view}
            onValueChange={(v) => set({ library_view: v })}
            options={[
              { value: 'grid', label: 'Cuadrícula' },
              { value: 'list', label: 'Lista' },
            ]}
          />
        </Field>
        <Field label="Reproducir al abrir un proyecto">
          <Switch label="Reproducir al abrir" checked={prefs.autoplay_on_open} onCheckedChange={(v) => set({ autoplay_on_open: v })} />
        </Field>
        <Field label="Reproducción en bucle">
          <Switch label="Bucle" checked={prefs.loop_playback} onCheckedChange={(v) => set({ loop_playback: v })} />
        </Field>
        <Field label="Recordar posición de reproducción" hint="Cada proyecto se reabre donde lo dejaste">
          <Switch label="Recordar posición" checked={prefs.remember_playback_position} onCheckedChange={(v) => set({ remember_playback_position: v })} />
        </Field>
        <Field label="Volumen inicial" hint="Para proyectos que aún no has reproducido">
          <Slider label="Volumen inicial" className="w-56" value={Math.round(prefs.default_volume * 100)} onValueChange={(v) => set({ default_volume: v / 100 })} format={(v) => `${v} %`} />
        </Field>
        <Field label="Proxy de reproducción" hint="Copia H.264 ligera para previsualizar. «Automático» solo la crea si el navegador no puede reproducir el códec (p. ej. ProRes).">
          <Segmented
            label="Proxy de reproducción"
            value={prefs.playback_proxy}
            onValueChange={(v) => set({ playback_proxy: v })}
            options={[
              { value: 'auto', label: 'Automático' },
              { value: 'always', label: 'Siempre' },
              { value: 'never', label: 'Nunca' },
            ]}
          />
        </Field>
      </div>
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Presets
// ---------------------------------------------------------------------------

function PresetEditor({
  preset,
  onClose,
  base,
}: {
  preset: Preset | null
  base: { name: string; config: EditConfig; description: string } | null
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { data: catalog } = useCatalog()
  const open = preset !== null || base !== null
  const initial = preset ?? base
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [config, setConfig] = useState<EditConfig | null>(initial?.config ?? null)
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!config) return
    setSaving(true)
    try {
      if (preset) await api.updatePreset(preset.id, { name: name.trim(), description, config })
      else await api.createPreset({ name: name.trim(), description, config })
      qc.invalidateQueries({ queryKey: keys.presets })
      toast.success(preset ? 'Preset actualizado' : 'Preset creado')
      onClose()
    } catch (err) {
      toast.error('No se pudo guardar', { description: errorText(err) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      size="lg"
      icon={<Pencil className="size-5" />}
      title={preset ? `Editar «${preset.name}»` : 'Nuevo preset'}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button variant="primary" loading={saving} disabled={!name.trim() || !config} onClick={submit}>
            {preset ? 'Guardar cambios' : 'Crear preset'}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3 pb-3">
        <Field label="Nombre" stacked htmlFor="preset-editor-name">
          <Input id="preset-editor-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Descripción" stacked htmlFor="preset-editor-desc">
          <Input id="preset-editor-desc" value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} placeholder="Opcional" />
        </Field>
      </div>
      <div className="-mx-6 border-t border-line">
        {catalog && config && <ConfigForm config={config} onChange={setConfig} catalog={catalog} />}
      </div>
    </Dialog>
  )
}

export function PresetsSection() {
  const qc = useQueryClient()
  const { data: presets } = usePresets()
  const { data: catalog } = useCatalog()
  const [editing, setEditing] = useState<Preset | null>(null)
  const [creating, setCreating] = useState<{ name: string; config: EditConfig; description: string } | null>(null)
  const [deleting, setDeleting] = useState<Preset | null>(null)

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      qc.invalidateQueries({ queryKey: keys.presets })
      qc.invalidateQueries({ queryKey: keys.settings })
      toast.success(ok)
    } catch (err) {
      toast.error('No se pudo completar', { description: errorText(err) })
    }
  }

  const startNew = (style: StyleId) => {
    const base = presets?.find((p) => p.is_builtin && p.style_id === style)
    if (!base) return
    setCreating({ name: '', description: '', config: structuredClone(base.config) })
  }

  return (
    <Section
      title="Presets de edición"
      description="Combinaciones reutilizables de estilo, subtítulos, animaciones, audio y exportación. Los integrados son de solo lectura: duplícalos para personalizarlos."
      actions={
        catalog && (
          <Menu
            items={catalog.styles.map((s) => ({ label: `Basado en ${s.name}`, onSelect: () => startNew(s.id) }))}
            trigger={
              <Button variant="primary" size="sm" icon={<Plus className="size-3.5" />}>
                Nuevo preset
              </Button>
            }
          />
        )
      }
    >
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3">
        {presets?.map((p) => (
          <li key={p.id} className="group overflow-hidden rounded-xl border border-line bg-surface-2 transition hover:border-line-strong">
            <StylePreview style={p.style_id} config={p.config.style} className="block aspect-[16/7] w-full" />
            <div className="p-3.5">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <h3 className="truncate text-[13.5px] font-semibold text-fg">{p.name}</h3>
                    {p.is_default && <Star className="size-3.5 shrink-0 fill-warning text-warning" aria-label="Predeterminado" />}
                  </div>
                  <p className="mt-0.5 flex items-center gap-1.5 text-xs text-fg-faint">
                    <span className="size-1.5 rounded-full ring-1 ring-line-strong" style={{ background: STYLE_META[p.style_id].color }} />
                    {STYLE_META[p.style_id].name}
                    {p.is_builtin && ' · integrado'}
                  </p>
                </div>
                <Menu
                  items={[
                    { label: 'Editar', icon: <Pencil />, disabled: p.is_builtin, onSelect: () => setEditing(p) },
                    { label: 'Duplicar', icon: <Copy />, onSelect: () => run(() => api.duplicatePreset(p.id), 'Preset duplicado') },
                    { label: 'Usar por defecto', icon: <Star />, disabled: p.is_default, onSelect: () => run(() => api.setDefaultPreset(p.id), `«${p.name}» es ahora el predeterminado`) },
                    { label: 'Eliminar', icon: <Trash />, danger: true, disabled: p.is_builtin, separatorBefore: true, onSelect: () => setDeleting(p) },
                  ]}
                  trigger={
                    <Button size="icon-sm" variant="ghost" aria-label={`Acciones de ${p.name}`}>
                      <Ellipsis className="size-4" />
                    </Button>
                  }
                />
              </div>
              {p.description && <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-fg-muted">{p.description}</p>}
              <div className="mt-3 flex flex-wrap gap-1">
                <Badge className="h-5 text-[10.5px]">{p.config.subtitles.enabled ? p.config.subtitles.font_family : 'Sin subtítulos'}</Badge>
                <Badge className="h-5 text-[10.5px]">Animación {p.config.animations.intensity === 'low' ? 'baja' : p.config.animations.intensity === 'medium' ? 'media' : 'alta'}</Badge>
                <Badge className="h-5 text-[10.5px]">{p.config.export.resolution === 'original' ? 'Res. original' : p.config.export.resolution}</Badge>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {(editing || creating) && <PresetEditor key={editing?.id ?? 'new'} preset={editing} base={creating} onClose={() => { setEditing(null); setCreating(null) }} />}
      <Dialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        tone="danger"
        icon={<Trash className="size-5" />}
        title="Eliminar preset"
        description={deleting && `Se eliminará «${deleting.name}». Los proyectos que lo usaban conservan su configuración actual.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancelar
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (deleting) void run(() => api.deletePreset(deleting.id), 'Preset eliminado')
                setDeleting(null)
              }}
            >
              Eliminar
            </Button>
          </>
        }
      />
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Estilos
// ---------------------------------------------------------------------------

export function StylesSection() {
  const { data: catalog } = useCatalog()
  return (
    <Section title="Estilos de edición" description="Cada estilo define su propio lenguaje visual, movimiento, composición y ritmo. Claude Opus 5.5 los aplica como director creativo al planificar la edición (pestaña Plan IA).">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {catalog?.styles.map((s) => (
          <article key={s.id} className="overflow-hidden rounded-xl border border-line bg-surface-2">
            <StylePreview style={s.id} className="block aspect-[16/10] w-full" />
            <div className="space-y-2.5 p-4 text-xs leading-relaxed text-fg-muted">
              <div>
                <h3 className="text-[15px] font-semibold text-fg">{s.name}</h3>
                <p className="text-[13px] text-fg-muted">{s.tagline}</p>
              </div>
              <p>{s.description}</p>
              <div className="flex gap-1.5">
                {s.palette.map((c) => (
                  <span key={c} className="size-5 rounded-md border border-line-strong" style={{ background: c }} title={c} />
                ))}
              </div>
              <Detail label="Tipografía">{s.typography}</Detail>
              <Detail label="Movimiento">{s.motion_language}</Detail>
              <Detail label="Composición">{s.composition}</Detail>
              <Detail label="Ritmo">{s.pacing}</Detail>
              <div className="flex flex-wrap gap-1 pt-1">
                {s.best_for.map((b) => (
                  <Badge key={b} className="h-5 text-[10.5px]">
                    {b}
                  </Badge>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
    </Section>
  )
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <p>
      <span className="font-medium text-fg">{label}: </span>
      {children}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Entorno
// ---------------------------------------------------------------------------

export function EnvironmentSection() {
  const { data: info, isLoading } = useSystemInfo()
  if (isLoading || !info) return <Section title="Entorno local"><Spinner /></Section>
  const rows: [string, ReactNode][] = [
    ['Aplicación', `${info.app.name} ${info.app.version} · Fase ${info.app.phase}`],
    ['Sistema', `${info.os} · ${info.arch}`],
    ['Procesador', `${info.cpu}${info.cpu_count ? ` · ${info.cpu_count} núcleos` : ''}`],
    ['Memoria', formatBytes(info.memory_bytes, 0)],
    ['Python', info.python],
    ['Node.js', info.node ?? 'No detectado'],
    ['FFmpeg', info.ffmpeg.version ? `${info.ffmpeg.version} · ${info.ffmpeg.path}` : 'No encontrado'],
    ['ffprobe', info.ffmpeg.ffprobe_version ?? 'No encontrado'],
    ['Aceleración', info.ffmpeg.hardware_encoders.length ? info.ffmpeg.hardware_encoders.join(', ') : 'Solo software (libx264)'],
    ['Servidor', `http://${info.server.host}:${info.server.port} (solo local)`],
    ['Datos de la app', info.paths.app_home],
    ['Base de datos', `${info.paths.database} · ${formatBytes(info.paths.database_bytes)} · integridad ${info.database.integrity}`],
    ['Registros', info.paths.logs ?? '—'],
  ]
  return (
    <Section title="Entorno local" description="Información de diagnóstico de este equipo.">
      <dl className="divide-y divide-line">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[160px_minmax(0,1fr)] gap-4 py-2 text-[13px]">
            <dt className="text-fg-faint">{k}</dt>
            <dd className="break-all text-fg">{v}</dd>
          </div>
        ))}
      </dl>
      <h3 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wider text-fg-faint">Capacidades</h3>
      <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {info.capabilities.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-3.5 py-2.5 text-[13px]">
            <span className={c.available ? 'text-fg' : 'text-fg-muted'}>{c.name}</span>
            {c.available ? (
              <Badge tone="success" icon={<CircleCheck className="size-3" />}>
                Operativa
              </Badge>
            ) : (
              <FutureBadge phase={c.phase} />
            )}
          </li>
        ))}
      </ul>
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Transcripción y análisis (Fase 2)
// ---------------------------------------------------------------------------

export function AnalysisSettingsSection() {
  const qc = useQueryClient()
  const { data: models } = useAsrModels()
  const { data: prefs } = useAnalysisSettings()
  const save = async (patch: Partial<AnalysisPreferences>) => {
    if (!prefs) return
    const next = { ...prefs, ...patch }
    qc.setQueryData(keys.analysisSettings, next)
    try {
      await api.saveAnalysisSettings(next)
    } catch (err) {
      toast.error('No se pudo guardar', { description: errorText(err) })
      qc.invalidateQueries({ queryKey: keys.analysisSettings })
    }
  }
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      qc.invalidateQueries({ queryKey: keys.asrModels })
      qc.invalidateQueries({ queryKey: keys.jobs })
    } catch (err) {
      toast.error('No se pudo completar', { description: errorText(err) })
    }
  }
  return (
    <Section
      title="Transcripción y análisis"
      description="Todo se procesa en este equipo. Cambiar estos valores no reprocesa nada por sí solo: al volver a analizar se genera un resultado nuevo (los anteriores quedan en el historial)."
    >
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-faint">
        Modelos de reconocimiento de voz{models ? ` (${models.engines.filter((e) => e.available).map((e) => e.name).join(' · ') || 'sin motor'})` : ''}
      </h3>
      {models && !models.supported && (
        <p className="mb-3 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">No hay ningún motor de transcripción local disponible en este equipo. Ejecuta el instalador de nuevo.</p>
      )}
      <ul className="space-y-2">
        {models?.models.map((m) => (
          <li key={m.id} className="rounded-xl border border-line bg-surface-2 p-3.5">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13.5px] font-semibold text-fg">{m.name}</span>
                  {m.recommended && <Badge tone="accent">Recomendado</Badge>}
                  {m.installed && <Badge tone="success" icon={<CircleCheck className="size-3" />}>Instalado</Badge>}
                  {prefs?.transcription_model === m.id && <Badge>En uso</Badge>}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-fg-muted">{m.description}</p>
                <a href={m.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[11px] text-accent hover:underline">
                  {m.repo} @ {m.revision.slice(0, 10)} · {formatBytes(m.size_bytes)}
                  {m.license ? ` · licencia ${m.license}` : ''}
                </a>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {prefs?.transcription_model !== m.id && (
                  <Button size="sm" variant="ghost" onClick={() => void save({ transcription_model: m.id as AnalysisPreferences['transcription_model'] })}>
                    Usar
                  </Button>
                )}
                {m.installed ? (
                  <Button size="sm" variant="ghost" icon={<Trash className="size-3.5" />} onClick={() => act(() => api.deleteModel(m.id))}>
                    Eliminar
                  </Button>
                ) : m.job ? null : (
                  <Button size="sm" variant="secondary" disabled={!models.supported} onClick={() => act(() => api.downloadModel(m.id))}>
                    Descargar
                  </Button>
                )}
              </div>
            </div>
            {m.job && (
              <div className="mt-3">
                <div className="mb-1 flex justify-between text-xs text-fg-muted">
                  <span>{m.job.stage ?? 'Descargando'}</span>
                  <span className="tabular">{Math.round(m.job.progress * 100)} %</span>
                </div>
                <ProgressBar value={m.job.progress} label={`Descarga de ${m.name}`} />
              </div>
            )}
          </li>
        ))}
      </ul>
      {prefs && (
        <div className="mt-5 divide-y divide-line">
          <Field label="Idioma del audio" hint="«Automático» detecta el idioma en cada tramo.">
            <Select
              label="Idioma"
              value={prefs.language}
              onValueChange={(v) => void save({ language: v })}
              options={[
                { value: 'auto', label: 'Automático' },
                { value: 'es', label: 'Español' },
                { value: 'en', label: 'Inglés' },
                { value: 'pt', label: 'Portugués' },
                { value: 'fr', label: 'Francés' },
                { value: 'it', label: 'Italiano' },
                { value: 'de', label: 'Alemán' },
                { value: 'ca', label: 'Catalán' },
              ]}
            />
          </Field>
          <Field label="Sensibilidad de corte" hint="Puntuación mínima de cambio de plano. Más baja = detecta más cortes (y más falsos positivos).">
            <Slider label="Sensibilidad de corte" className="w-56" min={10} max={90} value={Math.round(prefs.scene_threshold * 100)} onValueChange={(v) => void save({ scene_threshold: v / 100 })} format={(v) => (v / 100).toFixed(2)} />
          </Field>
          <Field label="Duración mínima de escena">
            <Slider label="Duración mínima de escena" className="w-56" min={2} max={50} value={Math.round(prefs.min_scene_seconds * 10)} onValueChange={(v) => void save({ min_scene_seconds: v / 10 })} format={(v) => `${(v / 10).toFixed(1)} s`} />
          </Field>
          <Field label="Intervalo estático mínimo" hint="Tiempo sin cambios visibles para considerarlo estático.">
            <Slider label="Intervalo estático mínimo" className="w-56" min={5} max={300} value={Math.round(prefs.static_min_seconds * 10)} onValueChange={(v) => void save({ static_min_seconds: v / 10 })} format={(v) => `${(v / 10).toFixed(1)} s`} />
          </Field>
          <Field label="Fotograma cada" hint="Además de inicio, centro y final de cada escena.">
            <Slider label="Intervalo de fotogramas" className="w-56" min={1} max={120} value={prefs.frame_interval_seconds} onValueChange={(v) => void save({ frame_interval_seconds: v })} format={(v) => `${v} s`} />
          </Field>
          <Field label="Máximo de fotogramas" hint="En exFAT cada imagen ocupa al menos 1 MB.">
            <Slider label="Máximo de fotogramas" className="w-56" min={10} max={1000} step={10} value={prefs.max_frames} onValueChange={(v) => void save({ max_frames: v })} />
          </Field>
          <Field label="Detectar rostros" hint="YuNet (OpenCV, local). Detecta presencia y posición, no identidad ni quién habla.">
            <Switch label="Detectar rostros" checked={prefs.detect_faces} onCheckedChange={(v) => void save({ detect_faces: v })} />
          </Field>
        </div>
      )}
    </Section>
  )
}
