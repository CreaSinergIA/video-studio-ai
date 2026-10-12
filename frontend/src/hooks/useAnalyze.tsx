import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Download, ExternalLink, Wand } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ProgressBar } from '@/components/ui/feedback'
import { keys, useAnalysisSettings, useAsrModels } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import type { Asset } from '@/lib/types'

export type AnalyzeKind = 'all' | 'transcript' | 'visual'

/**
 * Lanza el análisis del proyecto. Si hace falta transcribir y el modelo elegido no está
 * instalado, muestra un diálogo para descargarlo de forma explícita (tamaño y fuente a la
 * vista) o analizar solo las escenas.
 */
export function useAnalyze(projectId: string, asset: Asset | null) {
  const qc = useQueryClient()
  const { data: models } = useAsrModels()
  const { data: prefs } = useAnalysisSettings()
  const [busy, setBusy] = useState(false)
  const [needModel, setNeedModel] = useState<AnalyzeKind | null>(null)
  const modelId = prefs?.transcription_model ?? 'large-v3-turbo'
  const model = models?.models.find((m) => m.id === modelId)

  const run = async (kind: AnalyzeKind) => {
    setBusy(true)
    try {
      await api.analyze(projectId, { transcribe: kind !== 'visual', visual: kind !== 'transcript' })
      qc.invalidateQueries({ queryKey: keys.jobs })
      qc.invalidateQueries({ queryKey: keys.project(projectId) })
      toast.success('Análisis en marcha', { description: 'Puedes seguir trabajando; el progreso aparece arriba.' })
    } catch (err) {
      toast.error('No se pudo iniciar el análisis', { description: err instanceof ApiError ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  const start = (kind: AnalyzeKind = 'all') => {
    const transcribe = kind !== 'visual' && Boolean(asset?.has_audio)
    if (transcribe && models && (!models.supported || !model?.installed)) {
      setNeedModel(kind)
      return
    }
    void run(kind)
  }

  const download = async () => {
    try {
      await api.downloadModel(modelId)
      qc.invalidateQueries({ queryKey: keys.asrModels })
    } catch (err) {
      toast.error('No se pudo iniciar la descarga', { description: err instanceof ApiError ? err.message : String(err) })
    }
  }

  const job = model?.job
  const dialog = (
    <Dialog
      open={needModel !== null}
      onOpenChange={(o) => !o && setNeedModel(null)}
      icon={<Download className="size-5" />}
      title={models && !models.supported ? 'Transcripción no disponible en este equipo' : 'Falta el modelo de transcripción'}
      description={
        models && !models.supported
          ? 'La transcripción local usa MLX y requiere un Mac con Apple Silicon. Puedes analizar las escenas igualmente.'
          : 'La transcripción se hace en este Mac, sin enviar audio a ningún servicio. Para ello hay que descargar una vez el modelo; después funciona sin conexión.'
      }
      footer={
        <>
          <Button variant="ghost" onClick={() => setNeedModel(null)}>
            Cerrar
          </Button>
          {needModel !== 'transcript' && (
            <Button
              variant="secondary"
              onClick={() => {
                setNeedModel(null)
                void run('visual')
              }}
            >
              Analizar solo escenas
            </Button>
          )}
          {model?.installed && (
            <Button
              variant="primary"
              icon={<Wand className="size-4" />}
              onClick={() => {
                const kind = needModel ?? 'all'
                setNeedModel(null)
                void run(kind)
              }}
            >
              Analizar ahora
            </Button>
          )}
        </>
      }
    >
      {model && models?.supported && (
        <div className="space-y-3 rounded-xl border border-line bg-surface-2 p-4 text-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="font-semibold text-fg">{model.name}</div>
              <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{model.description}</p>
            </div>
            <span className="shrink-0 text-xs font-medium tabular text-fg">{formatBytes(model.size_bytes)}</span>
          </div>
          <a href={model.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
            Fuente: {model.repo} @ {model.revision.slice(0, 10)} <ExternalLink className="size-3" />
          </a>
          <p className="text-xs text-fg-faint">Cada archivo se verifica con su huella SHA-256 publicada. Se guarda en el disco interno.</p>
          {model.installed ? (
            <p className="text-xs font-medium text-success">Modelo instalado y verificado.</p>
          ) : job ? (
            <div>
              <div className="mb-1 text-xs text-fg-muted">
                {job.stage ?? 'Descargando'} · {Math.round(job.progress * 100)} %
              </div>
              <ProgressBar value={job.progress} label="Descarga del modelo" />
            </div>
          ) : (
            <Button variant="primary" icon={<Download className="size-4" />} onClick={download}>
              Descargar modelo ({formatBytes(model.size_bytes)})
            </Button>
          )}
        </div>
      )}
    </Dialog>
  )
  return { start, busy, dialog }
}
