import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, CircleAlert, CircleCheck, CircleDashed, Download, FolderOpen, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { StoragePicker } from '@/components/settings/StoragePicker'
import { ClaudeKeyForm, ClaudePricing } from '@/components/settings/ClaudeKeyForm'
import { Button } from '@/components/ui/Button'
import { Badge, ProgressBar, Spinner } from '@/components/ui/feedback'
import { keys, useAsrModels, useEngine, useSetupStatus, useStorageStatus } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'
import type { SetupCheck } from '@/lib/types'

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

const setupKey = keys.setup

const STEPS = [
  { id: 'storage', label: 'Proyectos' },
  { id: 'checks', label: 'Equipo' },
  { id: 'claude', label: 'Claude' },
  { id: 'done', label: 'Listo' },
] as const

function StatusIcon({ status }: { status: SetupCheck['status'] }) {
  if (status === 'ok') return <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" />
  if (status === 'error') return <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" />
  return <CircleDashed className="mt-0.5 size-4 shrink-0 text-warning" />
}

function StorageStep() {
  const { data: storage } = useStorageStatus()
  const [changing, setChanging] = useState(false)
  const configured = storage?.configured && storage.available
  return (
    <div>
      <h2 className="text-lg font-semibold text-fg">¿Dónde guardamos tus proyectos?</h2>
      <p className="mt-1 text-sm leading-relaxed text-fg-muted">
        Elige una carpeta dedicada (puede estar en un disco externo). Allí vivirán las copias de tus videos, transcripciones, planes, animaciones y exportaciones. Los originales nunca se modifican.
      </p>
      <div className="mt-5 rounded-2xl border border-line bg-surface-1 p-5">
        {configured && !changing ? (
          <div className="flex flex-wrap items-center gap-3">
            <FolderOpen className="size-5 text-success" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">Carpeta configurada</p>
              <p className="truncate font-mono text-xs text-fg-muted">{storage.path}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setChanging(true)}>
              Cambiar
            </Button>
          </div>
        ) : (
          <StoragePicker submitLabel="Usar esta carpeta" onConfigured={() => setChanging(false)} />
        )}
      </div>
    </div>
  )
}

function EngineAction() {
  const qc = useQueryClient()
  const { data: st } = useEngine()
  if (!st) return null
  if (st.job)
    return (
      <div className="mt-2">
        <ProgressBar value={st.job.progress} label="Descarga del navegador de render" />
        <p className="mt-1 text-xs text-fg-muted">{st.job.stage ?? 'Descargando'} · {Math.round(st.job.progress * 100)} %</p>
      </div>
    )
  if (st.browser.installed || st.remotion.installed !== st.remotion.expected) return null
  return (
    <Button
      className="mt-2"
      size="sm"
      variant="secondary"
      icon={<Download className="size-3.5" />}
      onClick={async () => {
        try {
          await api.installEngine()
          qc.invalidateQueries({ queryKey: keys.engine })
        } catch (err) {
          toast.error('No se pudo iniciar la descarga', { description: errorText(err) })
        }
      }}
    >
      Instalar navegador de render ({formatBytes(st.browser.download_bytes)})
    </Button>
  )
}

function ModelAction() {
  const qc = useQueryClient()
  const { data } = useAsrModels()
  if (!data) return null
  const model = data.models.find((m) => m.id === data.default_model) ?? data.models[0]
  if (!model || model.installed) return null
  if (model.job)
    return (
      <div className="mt-2">
        <ProgressBar value={model.job.progress} label={`Descarga de ${model.name}`} />
        <p className="mt-1 text-xs text-fg-muted">{model.job.stage ?? 'Descargando'} · {Math.round(model.job.progress * 100)} %</p>
      </div>
    )
  return (
    <div className="mt-2">
      <Button
        size="sm"
        variant="secondary"
        icon={<Download className="size-3.5" />}
        onClick={async () => {
          try {
            await api.downloadModel(model.id)
            qc.invalidateQueries({ queryKey: keys.asrModels })
          } catch (err) {
            toast.error('No se pudo iniciar la descarga', { description: errorText(err) })
          }
        }}
      >
        Descargar {model.name} ({formatBytes(model.size_bytes)})
      </Button>
      <p className="mt-1 text-xs text-fg-faint">Otros modelos (más ligeros o más precisos) en Ajustes → Transcripción.</p>
    </div>
  )
}

function ChecksStep() {
  const qc = useQueryClient()
  const { data, isFetching } = useSetupStatus()
  const { data: engine } = useEngine()
  const { data: models } = useAsrModels()
  const busy = Boolean(engine?.job) || Boolean(models?.models.some((m) => m.job))
  const checks = (data?.checks ?? []).filter((c) => c.id !== 'claude' && c.id !== 'panel')
  return (
    <div>
      <h2 className="text-lg font-semibold text-fg">Comprobación del equipo</h2>
      <p className="mt-1 text-sm leading-relaxed text-fg-muted">
        Todo se procesa en este equipo. Si falta algo, puedes prepararlo aquí o más tarde desde Ajustes.
      </p>
      <ul className="mt-5 space-y-2">
        {checks.map((c) => (
          <li key={c.id} className="rounded-xl border border-line bg-surface-1 p-3.5">
            <div className="flex items-start gap-2.5">
              <StatusIcon status={c.status} />
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-medium text-fg">{c.label}</p>
                <p className="break-words text-xs text-fg-muted">{c.detail}</p>
                {c.fix && <p className="mt-0.5 text-xs text-fg-faint">{c.fix}</p>}
                {c.id === 'remotion' && <EngineAction />}
                {c.id === 'transcription' && <ModelAction />}
                {c.id === 'ffmpeg' && c.status !== 'ok' && (
                  <p className="mt-1 text-xs text-warning">Vuelve a ejecutar el instalador («Instalar Video Studio AI»): descargará FFmpeg portátil verificado.</p>
                )}
              </div>
            </div>
          </li>
        ))}
        {!data && (
          <li className="flex items-center gap-2 text-sm text-fg-muted">
            <Spinner /> Comprobando…
          </li>
        )}
      </ul>
      <Button
        className="mt-3"
        size="sm"
        variant="ghost"
        loading={isFetching}
        disabled={busy}
        onClick={() => {
          qc.invalidateQueries({ queryKey: setupKey })
          qc.invalidateQueries({ queryKey: keys.engine })
          qc.invalidateQueries({ queryKey: keys.asrModels })
        }}
      >
        Volver a comprobar
      </Button>
    </div>
  )
}

function ClaudeStep() {
  return (
    <div>
      <h2 className="text-lg font-semibold text-fg">Conexión con Claude</h2>
      <p className="mt-1 text-sm leading-relaxed text-fg-muted">
        Claude Opus 5.5 actúa como director creativo: propone el plan de edición y la dirección de las animaciones, que tú revisas y apruebas. Usa <strong className="font-medium text-fg">tu propia clave de API</strong> de Anthropic. Es opcional: sin ella puedes importar, transcribir, subtitular y exportar.
      </p>
      <div className="mt-5 space-y-4 rounded-2xl border border-line bg-surface-1 p-5">
        <ClaudeKeyForm compact />
        <ClaudePricing />
        <p className="text-xs leading-relaxed text-fg-faint">
          Nada se envía sin que lo pidas. Cada operación muestra antes cuántas solicitudes necesita y hay un límite de solicitudes en 24 horas que puedes ajustar en Ajustes → Claude.
          Se envían la transcripción, datos de escenas y unos pocos fotogramas reducidos; nunca el archivo de video.
        </p>
      </div>
    </div>
  )
}

function DoneStep() {
  const { data } = useSetupStatus()
  const pending = (data?.checks ?? []).filter((c) => c.status !== 'ok')
  return (
    <div>
      <h2 className="text-lg font-semibold text-fg">Todo listo</h2>
      <p className="mt-1 text-sm leading-relaxed text-fg-muted">
        Importa un video vertical u horizontal, transcríbelo y, si quieres, pide a Claude un plan de edición. Puedes cambiar cualquier ajuste más tarde.
      </p>
      {pending.length > 0 && (
        <div className="mt-4 rounded-xl border border-warning/25 bg-warning/5 p-3.5 text-[13px]">
          <p className="font-medium text-fg">Pendiente (puedes completarlo desde Ajustes):</p>
          <ul className="mt-1 list-disc pl-5 text-fg-muted">
            {pending.map((c) => (
              <li key={c.id}>
                {c.label}: {c.fix || c.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!data?.storage_configured && <p className="mt-3 text-[13px] text-warning">Aún no has elegido la carpeta de proyectos: el editor te la pedirá al entrar.</p>}
      <p className="mt-4 text-xs text-fg-faint">Datos de la aplicación en <span className="font-mono">{data?.data_dir}</span></p>
    </div>
  )
}

/** Primera ejecución: carpeta de proyectos, comprobaciones del equipo y conexión con Claude. */
export function SetupPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [finishing, setFinishing] = useState(false)
  const finish = async () => {
    setFinishing(true)
    try {
      await api.completeSetup(true)
      await qc.invalidateQueries({ queryKey: setupKey })
      navigate('/')
    } catch (err) {
      toast.error('No se pudo guardar', { description: errorText(err) })
    } finally {
      setFinishing(false)
    }
  }
  const current = STEPS[step]
  return (
    <div className="h-full overflow-y-auto bg-glow">
      <div className="mx-auto max-w-3xl px-8 py-12 animate-rise">
        <div className="mb-8 flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-fg-muted">
              <Sparkles className="size-3.5 text-accent" />
              Primera configuración
            </div>
            <h1 className="text-3xl font-semibold tracking-tight text-fg">Bienvenido a Video Studio AI</h1>
            <p className="mt-2 text-[15px] text-fg-muted">Community Edition · edición de video asistida por IA, en tu equipo.</p>
          </div>
          <Button variant="ghost" size="sm" loading={finishing} onClick={() => void finish()}>
            Omitir y configurar después
          </Button>
        </div>
        <ol className="mb-8 flex gap-2" aria-label="Pasos">
          {STEPS.map((s, i) => (
            <li key={s.id} className="flex-1">
              <button
                type="button"
                onClick={() => setStep(i)}
                aria-current={i === step ? 'step' : undefined}
                className={cn('w-full rounded-lg border-t-2 pt-2 text-left text-xs font-medium transition', i <= step ? 'border-accent text-fg' : 'border-line text-fg-faint hover:text-fg-muted')}
              >
                {i + 1}. {s.label}
              </button>
            </li>
          ))}
        </ol>
        {current.id === 'storage' && <StorageStep />}
        {current.id === 'checks' && <ChecksStep />}
        {current.id === 'claude' && <ClaudeStep />}
        {current.id === 'done' && <DoneStep />}
        <div className="mt-8 flex items-center gap-2">
          {step > 0 && (
            <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={() => setStep(step - 1)}>
              Atrás
            </Button>
          )}
          <div className="ml-auto flex items-center gap-2">
            {current.id === 'claude' && <Badge>Opcional</Badge>}
            {step < STEPS.length - 1 ? (
              <Button variant="primary" icon={<ArrowRight className="size-4" />} onClick={() => setStep(step + 1)}>
                {current.id === 'claude' ? 'Continuar' : 'Siguiente'}
              </Button>
            ) : (
              <Button variant="primary" loading={finishing} onClick={() => void finish()}>
                Ir al editor
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
