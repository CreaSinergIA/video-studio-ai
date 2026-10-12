import { useState } from 'react'
import { Check, ChevronDown, CircleAlert, Clock, MessageSquareText, Shuffle, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/feedback'
import { Select } from '@/components/ui/fields'
import { cn } from '@/lib/cn'
import { LAYOUT, STATUS_META, SUBTITLES, TIMING, TYPE_META, TYPE_ORDER, fmtT } from '@/lib/plan'
import type { AnalysisFrame, InterventionStatus, InterventionType, PlanIntervention } from '@/lib/types'
import { CompositionPreview } from './CompositionPreview'

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-fg-faint">{label}</div>
      <div className="text-[12.5px] leading-relaxed text-fg-muted">{children}</div>
    </div>
  )
}

export function InterventionCard({
  item,
  index,
  frames,
  aspect,
  selected,
  busy,
  onSelect,
  onSeek,
  onStatus,
  onType,
  onAlternative,
  onRevise,
}: {
  item: PlanIntervention
  index: number
  frames: Record<string, AnalysisFrame>
  aspect: number
  selected: boolean
  busy: boolean
  onSelect: () => void
  onSeek: (t: number) => void
  onStatus: (s: InterventionStatus) => void
  onType: (t: InterventionType) => void
  onAlternative: (instruction: string) => void
  onRevise: (instruction: string) => Promise<boolean>
}) {
  const [instruction, setInstruction] = useState('')
  const canSend = !busy && instruction.trim().length >= 2
  const send = async () => {
    if (!canSend) return
    // El texto solo se borra si Claude aceptó la solicitud (si no, se conserva para reintentar).
    if (await onRevise(instruction.trim())) setInstruction('')
  }
  const meta = TYPE_META[item.type]
  const st = STATUS_META[item.status]
  const refFrames = item.frame_ids.map((id) => frames[id]).filter(Boolean)
  const first = refFrames[0]
  return (
    <li
      id={`iv-${item.id}`}
      className={cn(
        'rounded-xl border bg-surface-2 transition',
        selected ? 'border-accent/60 shadow-[0_0_0_1px_var(--accent)]' : 'border-line hover:border-line-strong',
        item.status === 'rejected' && 'opacity-60',
      )}
      aria-label={`Intervención ${index + 1}: ${meta.label}`}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect())}
        className="flex cursor-pointer gap-3 p-3"
      >
        <div className="w-14 shrink-0">
          {first ? (
            <img src={first.url} alt="" className="w-full rounded-md object-cover ring-1 ring-white/10" style={{ aspectRatio: String(aspect) }} loading="lazy" />
          ) : (
            <div className="w-full rounded-md bg-surface-3" style={{ aspectRatio: String(aspect) }} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onSeek(item.start)
                onSelect()
              }}
              className="inline-flex items-center gap-1 rounded-md bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-fg hover:bg-surface-4"
              aria-label={`Ir a ${fmtT(item.start)}`}
              title="Ir a este momento"
            >
              <Clock className="size-3" />
              {fmtT(item.start)}–{fmtT(item.end)}
            </button>
            <span className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium" style={{ background: `${meta.color}22`, color: meta.color }}>
              {meta.short}
            </span>
            <Badge tone={st.tone} className="h-5 text-[10.5px]">
              {st.label}
            </Badge>
            {item.stale && (
              <Badge tone="warning" className="h-5 text-[10.5px]" icon={<CircleAlert className="size-3" />}>
                Obsoleta
              </Badge>
            )}
          </div>
          <p className="mt-1 text-[13px] font-medium leading-snug text-fg">{item.goal}</p>
          {item.transcript_excerpt && <p className="mt-0.5 line-clamp-2 text-xs italic leading-snug text-fg-faint">«{item.transcript_excerpt}»</p>}
        </div>
        <ChevronDown className={cn('mt-1 size-4 shrink-0 text-fg-faint transition', selected && 'rotate-180')} />
      </div>

      {selected && (
        <div className="space-y-3 border-t border-line px-3 pb-3 pt-3">
          {item.stale && <p className="rounded-lg bg-warning/10 px-2.5 py-1.5 text-xs text-warning">{item.stale_reason}</p>}
          <CompositionPreview item={item} frame={first} aspect={aspect} className="mx-auto max-h-64" />
          <Detail label="Qué se verá">{item.visual_description}</Detail>
          <div className="grid grid-cols-2 gap-3">
            <Detail label="Composición">
              {LAYOUT[item.composition.layout] ?? item.composition.layout}
              {item.composition.notes ? ` · ${item.composition.notes}` : ''}
            </Detail>
            <Detail label="Subtítulos">{SUBTITLES[item.subtitles]}</Detail>
            <Detail label="Movimiento">
              entra {item.motion.entry} ({item.motion.entry_seconds}s) · sale {item.motion.exit} · {item.motion.easing}
              {item.motion.camera !== 'none' ? ` · cámara ${item.motion.camera}` : ''}
            </Detail>
            <Detail label="Transiciones">
              {item.transitions.into} → {item.transitions.out} · intensidad {item.intensity}
            </Detail>
          </div>
          {item.motion.emphasis && <Detail label="Sincronía con la voz">{item.motion.emphasis}</Detail>}
          {item.elements.length > 0 && (
            <Detail label="Elementos">
              <ul className="space-y-0.5">
                {item.elements.map((e, i) => (
                  <li key={i}>
                    <span className="font-mono text-[11px] text-fg">{e.kind}</span>
                    {e.text ? <span className="text-fg"> «{e.text}»</span> : null} — {e.description}
                  </li>
                ))}
              </ul>
            </Detail>
          )}
          {item.sfx.length > 0 && (
            <Detail label="Efectos de sonido sugeridos">{item.sfx.map((s) => `${s.kind} @ ${fmtT(s.at)}`).join(' · ')}</Detail>
          )}
          <Detail label="Por qué (Claude)">{item.rationale}</Detail>
          <div className="grid grid-cols-2 gap-3">
            <Detail label="Hechos observados">
              <ul className="list-disc pl-4">{item.evidence.observed.map((o, i) => <li key={i}>{o}</li>)}</ul>
            </Detail>
            <Detail label="Inferencias del modelo">
              <ul className="list-disc pl-4">{item.evidence.inferred.map((o, i) => <li key={i}>{o}</li>)}</ul>
            </Detail>
          </div>
          {refFrames.length > 1 && (
            <Detail label="Fotogramas de referencia (reales)">
              <div className="flex gap-1.5">
                {refFrames.map((f) => (
                  <button key={f.id} type="button" onClick={() => onSeek(f.t)} title={`Ir a ${fmtT(f.t)}`}>
                    <img src={f.url} alt={`Fotograma en ${fmtT(f.t)}`} className="h-16 rounded object-cover ring-1 ring-white/10" style={{ aspectRatio: String(aspect) }} loading="lazy" />
                  </button>
                ))}
              </div>
            </Detail>
          )}
          <Detail label="Tiempo">
            {TIMING[item.timing]}
            {item.anchor_from_word ? ` (${item.anchor_from_word}–${item.anchor_to_word})` : ''} · confianza {item.confidence} · revisión {item.revision}
          </Detail>
          {item.warnings.length > 0 && (
            <div className="rounded-lg bg-surface-3 px-2.5 py-2 text-xs text-fg-muted">
              <div className="mb-0.5 font-semibold text-fg">Correcciones de la validación</div>
              <ul className="list-disc pl-4">{item.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-1.5">
            <Button size="sm" variant={item.status === 'accepted' ? 'primary' : 'secondary'} icon={<Check className="size-3.5" />} disabled={busy} onClick={() => onStatus(item.status === 'accepted' ? 'proposed' : 'accepted')}>
              {item.status === 'accepted' ? 'Aceptada' : 'Aceptar'}
            </Button>
            <Button size="sm" variant={item.status === 'rejected' ? 'danger' : 'secondary'} icon={<X className="size-3.5" />} disabled={busy} onClick={() => onStatus(item.status === 'rejected' ? 'proposed' : 'rejected')}>
              {item.status === 'rejected' ? 'Rechazada' : 'Rechazar'}
            </Button>
            <Button size="sm" variant="ghost" icon={<Shuffle className="size-3.5" />} disabled={busy} onClick={() => onAlternative(instruction)}>
              Alternativa
            </Button>
            <Select<InterventionType>
              label="Cambiar tipo de intervención"
              className="ml-auto w-44"
              value={item.type}
              disabled={busy}
              onValueChange={onType}
              options={TYPE_ORDER.map((t) => ({ value: t, label: TYPE_META[t].label }))}
            />
          </div>
          <div>
            <div className="flex gap-1.5">
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send()
                }}
                rows={2}
                placeholder="Pide un cambio para esta intervención (p. ej. «más minimalista», «no tapes mi cara»)…"
                className="min-w-0 flex-1 resize-none rounded-lg border border-line-strong bg-surface-1 p-2 text-[12.5px] leading-snug text-fg placeholder:text-fg-faint focus:border-accent focus:outline-none"
                aria-label="Instrucción para esta intervención"
              />
              <Button
                size="icon"
                variant="secondary"
                aria-label="Enviar corrección a Claude"
                title="Enviar a Claude (⌘↵)"
                disabled={!canSend}
                onClick={() => void send()}
              >
                <Sparkles className="size-4" />
              </Button>
            </div>
            <p className="mt-1 flex items-center gap-1 text-[11px] text-fg-faint">
              <MessageSquareText className="size-3" /> Claude solo modifica esta intervención; el resto del plan se conserva.
            </p>
          </div>
          {item.status_history.length > 1 && (
            <Detail label="Historial">
              <ol className="space-y-0.5 text-[11.5px]">
                {item.status_history.slice(-6).map((h, i) => (
                  <li key={i}>
                    {new Date(h.at).toLocaleString()} · {STATUS_META[h.status as InterventionStatus]?.label ?? h.status}
                    {h.note ? ` · ${h.note}` : ''}
                  </li>
                ))}
              </ol>
            </Detail>
          )}
        </div>
      )}
    </li>
  )
}
