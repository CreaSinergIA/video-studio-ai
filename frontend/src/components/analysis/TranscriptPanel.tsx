import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AudioLines,
  Check,
  Clock,
  Download,
  FileText,
  History,
  Pencil,
  Timer,
  TriangleAlert,
  Wand,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Badge, EmptyState, Tooltip } from '@/components/ui/feedback'
import { Select } from '@/components/ui/fields'
import { Menu } from '@/components/ui/Menu'
import { keys } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { formatDateTime, formatTimecode } from '@/lib/format'
import type { AnalysisState, Transcript, TranscriptSegment, TranscriptWord } from '@/lib/types'

const LANG: Record<string, string> = { es: 'Español', en: 'Inglés', pt: 'Portugués', fr: 'Francés', it: 'Italiano', de: 'Alemán', ca: 'Catalán' }
const errText = (e: unknown) => (e instanceof ApiError ? e.message : String(e))

function activeWordId(segments: TranscriptSegment[], t: number): string | null {
  // Búsqueda binaria sobre segmentos y lineal dentro del segmento.
  let lo = 0
  let hi = segments.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const s = segments[mid]
    if (t < s.start) hi = mid - 1
    else if (t > s.end + 0.25) lo = mid + 1
    else {
      const w = s.words.findLast((x) => x.start <= t)
      return w ? w.id : null
    }
  }
  return null
}

function TimesEditor({
  transcript,
  segment,
  getTime,
  onDone,
}: {
  transcript: Transcript
  segment: TranscriptSegment
  getTime: () => number
  onDone: () => void
}) {
  const qc = useQueryClient()
  const [rows, setRows] = useState(() => segment.words.map((w) => ({ id: w.id, text: w.text, start: w.start, end: w.end })))
  const [saving, setSaving] = useState(false)
  const set = (i: number, key: 'start' | 'end', v: number) =>
    setRows((r) => r.map((row, k) => (k === i ? { ...row, [key]: Math.round(v * 1000) / 1000 } : row)))
  const save = async () => {
    setSaving(true)
    try {
      await api.putSegmentTimes(transcript.id, segment.id, rows.map(({ id, start, end }) => ({ id, start, end })))
      await qc.invalidateQueries({ queryKey: ['analysis'] })
      await qc.invalidateQueries({ queryKey: ['track'] })
      toast.success('Tiempos guardados como «manuales»')
      onDone()
    } catch (err) {
      toast.error('No se pudieron guardar los tiempos', { description: errText(err) })
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="mt-3 rounded-lg border border-line bg-surface-1 p-2">
      <div className="mb-1 grid grid-cols-[minmax(0,1fr)_84px_84px] gap-1.5 px-1 text-[10.5px] uppercase tracking-wide text-fg-faint">
        <span>Palabra</span>
        <span>Inicio (s)</span>
        <span>Fin (s)</span>
      </div>
      <div className="max-h-56 space-y-1 overflow-y-auto">
        {rows.map((r, i) => (
          <div key={r.id} className="grid grid-cols-[minmax(0,1fr)_84px_84px] items-center gap-1.5">
            <span className="truncate px-1 text-xs text-fg">{r.text}</span>
            {(['start', 'end'] as const).map((k) => (
              <div key={k} className="flex">
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={r[k]}
                  onChange={(e) => set(i, k, Number(e.target.value))}
                  className="h-7 w-full min-w-0 rounded-l-md border border-line-strong bg-surface-2 px-1.5 text-xs tabular text-fg focus:border-accent focus:outline-none"
                  aria-label={`${k === 'start' ? 'Inicio' : 'Fin'} de «${r.text}»`}
                />
                <button
                  type="button"
                  title="Usar el tiempo actual del reproductor"
                  aria-label={`Usar tiempo actual como ${k === 'start' ? 'inicio' : 'fin'} de «${r.text}»`}
                  onClick={() => set(i, k, getTime())}
                  className="grid h-7 w-6 shrink-0 place-items-center rounded-r-md border border-l-0 border-line-strong bg-surface-3 text-fg-faint hover:text-fg"
                >
                  <Clock className="size-3" />
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancelar
        </Button>
        <Button size="sm" variant="primary" loading={saving} onClick={save}>
          Guardar tiempos
        </Button>
      </div>
    </div>
  )
}

const SegmentCard = memo(function SegmentCard({
  transcript,
  segment,
  activeWord,
  getTime,
  onSeek,
  realigning,
}: {
  transcript: Transcript
  segment: TranscriptSegment
  activeWord: string | null
  getTime: () => number
  onSeek: (t: number) => void
  realigning: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [timing, setTiming] = useState(false)
  const [text, setText] = useState(segment.text)
  const [saving, setSaving] = useState(false)
  const estimated = segment.words.filter((w) => w.timing === 'estimated').length
  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ['analysis'] })
    await qc.invalidateQueries({ queryKey: ['track'] })
  }
  const save = async () => {
    setSaving(true)
    try {
      await api.patchSegment(transcript.id, segment.id, { text })
      await refresh()
      setEditing(false)
    } catch (err) {
      toast.error('No se pudo guardar', { description: errText(err) })
    } finally {
      setSaving(false)
    }
  }
  const realign = async () => {
    try {
      await api.realign(transcript.id, [segment.id])
      qc.invalidateQueries({ queryKey: keys.jobs })
      toast.success('Realineando con el audio…', { description: 'Los tiempos medidos sustituirán a los estimados.' })
    } catch (err) {
      toast.error('No se pudo realinear', { description: errText(err) })
    }
  }
  const toggleReviewed = async () => {
    try {
      await api.patchSegment(transcript.id, segment.id, { reviewed: !segment.reviewed })
      await refresh()
    } catch (err) {
      toast.error('No se pudo marcar', { description: errText(err) })
    }
  }
  const containsActive = activeWord !== null
  return (
    <li
      data-segment={segment.id}
      className={cn(
        'group rounded-xl border px-3 py-2.5 transition',
        containsActive ? 'border-accent/40 bg-accent-soft/40' : 'border-transparent hover:border-line hover:bg-surface-2',
      )}
    >
      <div className="mb-1 flex items-center gap-2 text-[11px] text-fg-faint">
        <button type="button" onClick={() => onSeek(segment.start)} className="tabular hover:text-accent" title="Reproducir desde aquí">
          {formatTimecode(segment.start)} – {formatTimecode(segment.end)}
        </button>
        {segment.edited && <Badge className="h-[18px] px-1.5 text-[10px]" tone="accent">Corregido</Badge>}
        {segment.reviewed && <Badge className="h-[18px] px-1.5 text-[10px]" tone="success">Revisado</Badge>}
        <div className="ml-auto flex items-center gap-0.5 opacity-0 transition group-focus-within:opacity-100 group-hover:opacity-100">
          <Tooltip content={segment.reviewed ? 'Quitar marca de revisado' : 'Marcar como revisado'}>
            <button type="button" onClick={toggleReviewed} className="grid size-6 place-items-center rounded-md hover:bg-surface-4 hover:text-fg" aria-label="Marcar segmento revisado">
              <Check className="size-3.5" />
            </button>
          </Tooltip>
          <Tooltip content="Ajustar tiempos">
            <button type="button" onClick={() => setTiming((v) => !v)} className="grid size-6 place-items-center rounded-md hover:bg-surface-4 hover:text-fg" aria-label="Ajustar tiempos del segmento">
              <Timer className="size-3.5" />
            </button>
          </Tooltip>
          <Tooltip content="Corregir texto">
            <button
              type="button"
              onClick={() => {
                setText(segment.text)
                setEditing(true)
              }}
              className="grid size-6 place-items-center rounded-md hover:bg-surface-4 hover:text-fg"
              aria-label="Corregir texto del segmento"
            >
              <Pencil className="size-3.5" />
            </button>
          </Tooltip>
        </div>
      </div>
      {editing ? (
        <div>
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void save()
              if (e.key === 'Escape') setEditing(false)
            }}
            rows={Math.min(6, Math.max(2, Math.ceil(text.length / 40)))}
            className="w-full resize-y rounded-lg border border-line-strong bg-surface-1 p-2 text-[13.5px] leading-relaxed text-fg focus:border-accent focus:outline-none"
            aria-label="Texto del segmento"
          />
          <p className="mt-1 text-[11px] leading-snug text-fg-faint">
            Si solo cambias palabras, se conservan sus tiempos medidos. Si añades o quitas palabras, sus tiempos quedarán marcados como estimados para que los revises.
          </p>
          <div className="mt-2 flex justify-end gap-2">
            <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={() => setEditing(false)}>
              Cancelar
            </Button>
            <Button size="sm" variant="primary" loading={saving} onClick={save}>
              Guardar
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-[13.5px] leading-relaxed text-fg">
          {segment.words.map((w: TranscriptWord) => (
            <button
              key={w.id}
              type="button"
              onClick={() => onSeek(w.start)}
              title={`${formatTimecode(w.start)} → ${formatTimecode(w.end)}${w.original_text ? ` · original: «${w.original_text}»` : ''}${w.timing === 'estimated' ? ' · tiempo estimado' : ''}`}
              className={cn(
                'mr-[0.28em] rounded-[4px] px-[1px] transition-colors hover:bg-surface-4',
                activeWord === w.id && 'bg-accent text-accent-fg',
                w.edited && activeWord !== w.id && 'text-accent-strong underline decoration-accent/50 underline-offset-[3px]',
                w.timing === 'estimated' && 'underline decoration-warning decoration-dotted decoration-2 underline-offset-[3px]',
              )}
            >
              {w.text}
            </button>
          ))}
        </p>
      )}
      {segment.needs_timing_review && !editing && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-warning/25 bg-warning/[0.07] px-2.5 py-2 text-xs text-warning">
          <TriangleAlert className="size-3.5 shrink-0" />
          <span className="min-w-0 flex-1">
            {estimated} palabra{estimated === 1 ? '' : 's'} con tiempo estimado (no medido).
          </span>
          <Button size="sm" variant="secondary" loading={realigning} icon={<Wand className="size-3.5" />} onClick={realign}>
            Realinear con el audio
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setTiming(true)}>
            Ajustar a mano
          </Button>
        </div>
      )}
      {timing && <TimesEditor transcript={transcript} segment={segment} getTime={getTime} onDone={() => setTiming(false)} />}
    </li>
  )
})

export function TranscriptPanel({
  projectId,
  state,
  currentTime,
  onSeek,
  realignBusy,
  onAnalyze,
  analyzing,
}: {
  projectId: string
  state: AnalysisState | undefined
  currentTime: number
  onSeek: (t: number) => void
  realignBusy: boolean
  onAnalyze: () => void
  analyzing: boolean
}) {
  const qc = useQueryClient()
  const transcript = state?.transcript ?? null
  const [follow, setFollow] = useState(true)
  const listRef = useRef<HTMLUListElement>(null)
  const timeRef = useRef(currentTime)
  useEffect(() => {
    timeRef.current = currentTime
  }, [currentTime])
  const getTime = useCallback(() => timeRef.current, [])
  const active = useMemo(() => (transcript ? activeWordId(transcript.segments, currentTime) : null), [transcript, currentTime])
  const activeSeg = useMemo(() => transcript?.segments.find((s) => s.words.some((w) => w.id === active))?.id ?? null, [transcript, active])

  useEffect(() => {
    if (!follow || !activeSeg) return
    listRef.current?.querySelector(`[data-segment="${activeSeg}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeSeg, follow])

  if (!transcript) {
    return (
      <EmptyState
        icon={<AudioLines className="size-5" />}
        title="Sin transcripción"
        description="Analiza el video para transcribir el audio localmente con Whisper. Nada sale de este equipo."
        action={
          <Button variant="primary" loading={analyzing} icon={<Wand className="size-4" />} onClick={onAnalyze}>
            Analizar video
          </Button>
        }
      />
    )
  }
  if (transcript.status !== 'ready') {
    return (
      <EmptyState
        icon={<AudioLines className="size-5" />}
        title={transcript.status === 'no_audio' ? 'El video no tiene audio' : 'No se detectó voz'}
        description={
          transcript.status === 'no_audio'
            ? 'No hay pista de audio que transcribir. El análisis de escenas sigue disponible.'
            : 'El audio no contiene voz reconocible (solo silencio o ruido).'
        }
      />
    )
  }

  const stats = transcript.stats
  const versions = state?.versions ?? []
  const switchVersion = async (id: string) => {
    try {
      await api.activateTranscript(id)
      qc.invalidateQueries({ queryKey: keys.analysis(projectId) })
      qc.invalidateQueries({ queryKey: ['track'] })
    } catch (err) {
      toast.error('No se pudo cambiar de versión', { description: errText(err) })
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 border-b border-line px-5 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={transcript.kind === 'edited' ? 'accent' : 'neutral'}>{transcript.kind === 'edited' ? 'Versión corregida' : 'Transcripción original'}</Badge>
          {transcript.language && <Badge>{LANG[transcript.language] ?? transcript.language}</Badge>}
          <Badge className="font-normal">{transcript.model}</Badge>
          <Menu
            items={[
              { label: 'Texto (.txt)', icon: <FileText />, onSelect: () => window.open(`/api/transcripts/${transcript.id}/export?format=txt`) },
              { label: 'Subtítulos SRT (.srt)', icon: <Download />, onSelect: () => window.open(`/api/transcripts/${transcript.id}/export?format=srt`) },
              { label: 'WebVTT (.vtt)', icon: <Download />, onSelect: () => window.open(`/api/transcripts/${transcript.id}/export?format=vtt`) },
            ]}
            trigger={
              <Button size="sm" variant="ghost" className="ml-auto" icon={<Download className="size-3.5" />}>
                Exportar
              </Button>
            }
          />
        </div>
        <p className="text-xs text-fg-faint">
          {stats.words ?? 0} palabras
          {stats.voice ? ` · voz ${Math.round(stats.voice.speech_ratio * 100)} %` : ''}
          {stats.realtime_factor ? ` · ${stats.realtime_factor}× tiempo real` : ''}
          {stats.estimated_words ? ` · ${stats.estimated_words} con tiempo estimado` : ''}
        </p>
        <div className="flex items-center gap-2">
          {versions.length > 1 && (
            <Select
              label="Versión de la transcripción"
              value={transcript.id}
              className="h-8 min-w-0 flex-1 text-xs"
              onValueChange={(v) => void switchVersion(v)}
              options={versions.map((v) => ({
                value: v.id,
                label: `${v.kind === 'edited' ? 'Corregida' : 'Original'} · ${formatDateTime(v.created_at)}`,
              }))}
            />
          )}
          {versions.length > 1 && <History className="size-4 shrink-0 text-fg-faint" aria-hidden />}
          <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-xs text-fg-muted">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[var(--accent)]" />
            Seguir reproducción
          </label>
        </div>
      </div>
      <ul ref={listRef} className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-3" aria-label="Segmentos de la transcripción">
        {transcript.segments.map((seg) => (
          <SegmentCard
            key={seg.id}
            transcript={transcript}
            segment={seg}
            activeWord={seg.id === activeSeg ? active : null}
            getTime={getTime}
            onSeek={onSeek}
            realigning={realignBusy}
          />
        ))}
      </ul>
      <p className="border-t border-line px-5 py-2 text-[11px] leading-snug text-fg-faint">
        Clic en una palabra para reproducir desde ella. <span className="underline decoration-accent/60">Subrayado</span>: corregida ·{' '}
        <span className="underline decoration-warning decoration-dotted">punteado</span>: tiempo estimado.
      </p>
    </div>
  )
}
