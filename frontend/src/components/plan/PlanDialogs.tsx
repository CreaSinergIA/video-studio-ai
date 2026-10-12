import { useState } from 'react'
import { History, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Badge } from '@/components/ui/feedback'
import { Segmented } from '@/components/ui/fields'
import { usePlanVersions, useUsage } from '@/hooks/queries'
import { formatRelative } from '@/lib/format'
import { LAYOUT, STATUS_META, SUBTITLES, TYPE_META, fmtT, isPassive } from '@/lib/plan'
import type { AnalysisFrame, PlanDocument } from '@/lib/types'
import { CompositionPreview } from './CompositionPreview'

// ---------------------------------------------------------------------------
// Storyboard conceptual (planificación, no render)
// ---------------------------------------------------------------------------

export function StoryboardDialog({
  open,
  onOpenChange,
  doc,
  frames,
  aspect,
  onSeek,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  doc: PlanDocument
  frames: Record<string, AnalysisFrame>
  aspect: number
  onSeek: (t: number) => void
}) {
  const [filter, setFilter] = useState<'all' | 'accepted'>('all')
  const items = doc.interventions.filter((i) => (filter === 'accepted' ? i.status === 'accepted' : i.status !== 'rejected'))
  const vertical = aspect < 1
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Storyboard del plan"
      description="Vista de planificación, no un render: las imágenes son fotogramas reales del video y los recuadros marcan dónde iría cada animación (en rojo discontinuo, los rostros protegidos)."
    >
      <div className="mb-3 flex items-center gap-3">
        <Segmented
          label="Filtro del storyboard"
          size="sm"
          value={filter}
          onValueChange={setFilter}
          options={[
            { value: 'all', label: 'Todas (sin rechazadas)' },
            { value: 'accepted', label: 'Solo aceptadas' },
          ]}
        />
        <span className="text-xs text-fg-faint">{items.length} paneles</span>
      </div>
      <ol className={`grid gap-4 ${vertical ? 'grid-cols-2 md:grid-cols-3' : 'grid-cols-1 md:grid-cols-2'}`}>
        {items.map((i, n) => {
          const meta = TYPE_META[i.type]
          const frame = i.frame_ids.map((id) => frames[id]).find(Boolean)
          return (
            <li key={i.id} className="flex flex-col rounded-xl border border-line bg-surface-2 p-2.5">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px]">
                <span className="font-semibold text-fg">#{n + 1}</span>
                <button type="button" className="font-mono text-fg-muted hover:text-accent" onClick={() => onSeek(i.start)}>
                  {fmtT(i.start)} → {fmtT(i.end)}
                </button>
                <span className="ml-auto rounded px-1.5 py-0.5 font-medium" style={{ background: `${meta.color}22`, color: meta.color }}>
                  {meta.short}
                </span>
              </div>
              <CompositionPreview item={i} frame={frame} aspect={aspect} />
              <p className="mt-2 text-[12.5px] font-medium leading-snug text-fg">{i.goal}</p>
              <p className="mt-1 line-clamp-6 text-[11.5px] leading-relaxed text-fg-muted">{i.visual_description}</p>
              {!isPassive(i) && (
                <dl className="mt-2 space-y-0.5 text-[11px] text-fg-faint">
                  <div>
                    <dt className="inline font-semibold text-fg-muted">Composición: </dt>
                    <dd className="inline">{LAYOUT[i.composition.layout] ?? i.composition.layout}</dd>
                  </div>
                  {i.elements.length > 0 && (
                    <div>
                      <dt className="inline font-semibold text-fg-muted">Elementos: </dt>
                      <dd className="inline">{i.elements.map((e) => (e.text ? `${e.kind} «${e.text}»` : e.kind)).join(', ')}</dd>
                    </div>
                  )}
                  <div>
                    <dt className="inline font-semibold text-fg-muted">Movimiento: </dt>
                    <dd className="inline">
                      entra {i.motion.entry} en {fmtT(i.start)} · sale {i.motion.exit} en {fmtT(i.end)} · {i.motion.easing}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline font-semibold text-fg-muted">Subtítulos: </dt>
                    <dd className="inline">{SUBTITLES[i.subtitles]}</dd>
                  </div>
                  {i.sfx.length > 0 && (
                    <div>
                      <dt className="inline font-semibold text-fg-muted">Sonido: </dt>
                      <dd className="inline">{i.sfx.map((s) => `${s.kind} ${fmtT(s.at)}`).join(', ')}</dd>
                    </div>
                  )}
                </dl>
              )}
              <div className="mt-auto pt-2">
                <Badge tone={STATUS_META[i.status].tone} className="h-5 text-[10.5px]">
                  {STATUS_META[i.status].label}
                </Badge>
              </div>
            </li>
          )
        })}
      </ol>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Versiones
// ---------------------------------------------------------------------------

const KIND: Record<string, string> = {
  generated: 'Generado por Claude',
  revision: 'Corrección de Claude',
  alternative: 'Alternativa de Claude',
  manual: 'Cambio manual',
  approval: 'Aprobación',
  refresh: 'Tiempos recalculados',
}

export function VersionsDialog({
  open,
  onOpenChange,
  projectId,
  onRestore,
  busy,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  projectId: string
  onRestore: (n: number) => void
  busy: boolean
}) {
  const { data } = usePlanVersions(projectId, open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg" title="Historial de versiones" icon={<History className="size-5" />} description="Cada cambio crea una versión nueva; nada se sobrescribe. Las versiones aprobadas son inmutables.">
      <ol className="space-y-2">
        {data?.map((v) => (
          <li key={v.number} className={`rounded-xl border p-3 ${v.current ? 'border-accent/50 bg-accent-soft/40' : 'border-line bg-surface-2'}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold text-fg">v{v.number}</span>
              <span className="text-[13px] text-fg">{KIND[v.kind] ?? v.kind}</span>
              {v.current && <Badge tone="accent">Actual</Badge>}
              {v.approved && <Badge tone="success">Aprobada</Badge>}
              {v.immutable && !v.approved && <Badge>Inmutable</Badge>}
              <span className="ml-auto text-xs text-fg-faint">{formatRelative(v.created_at)}</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-fg-muted">{v.summary}</p>
            {v.instruction && <p className="mt-1 text-xs italic text-fg-faint">Instrucción: «{v.instruction}»</p>}
            <div className="mt-1.5 flex items-center gap-2 text-[11px] text-fg-faint">
              <span>{v.interventions} intervenciones</span>
              {v.parent_number && <span>· deriva de v{v.parent_number}</span>}
              {!v.current && (
                <Button size="sm" variant="ghost" className="ml-auto h-7" icon={<RotateCcw className="size-3.5" />} disabled={busy} onClick={() => onRestore(v.number)}>
                  Restaurar
                </Button>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Consumo
// ---------------------------------------------------------------------------

const n = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toLocaleString('es'))

export function UsageDialog({ open, onOpenChange, projectId }: { open: boolean; onOpenChange: (v: boolean) => void; projectId: string }) {
  const { data } = useUsage(projectId, open)
  const subscription = data?.billing.includes('subscription')
  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="xl" title="Consumo de Claude en este proyecto" description="Datos que informa la propia integración por cada solicitud.">
      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {[
              ['Solicitudes', `${data.calls} (${data.ok} correctas)`],
              ['Errores / reintentos', `${data.errors} / ${data.retries}`],
              ['Tokens de entrada', n(data.input_tokens + data.cache_creation_tokens + data.cache_read_tokens)],
              ['Tokens de salida', n(data.output_tokens)],
              ['Escritos en caché', n(data.cache_creation_tokens)],
              ['Leídos de caché', n(data.cache_read_tokens)],
              ['Tiempo total', `${(data.duration_ms / 1000).toFixed(0)} s`],
              [subscription ? 'Coste estimado (no facturado)' : 'Coste', data.cost_estimate_usd !== null ? `≈ ${data.cost_estimate_usd.toFixed(2)} USD` : 'no disponible'],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line bg-surface-2 px-3 py-2">
                <div className="text-[10.5px] uppercase tracking-wider text-fg-faint">{k}</div>
                <div className="text-sm font-semibold tabular text-fg">{v}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed text-fg-muted">
            {subscription
              ? 'Conexión mediante Claude Code con tu plan: no hay cargos por solicitud; consume los límites de uso del plan. El coste es una estimación de Claude Code a precio de lista, útil solo como referencia.'
              : 'Conexión mediante la API: se factura por tokens en tu cuenta de Anthropic. El panel no calcula precios; consulta el importe real en la Consola.'}
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-fg-faint">
                <tr>
                  {['Fecha', 'Paso', 'Modelo · esfuerzo', 'Estado', 'Entrada', 'Salida', 'Caché', 'Duración', 'Enviado', 'Estimación'].map((h) => (
                    <th key={h} className="whitespace-nowrap px-2 py-1.5 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line text-fg-muted">
                {data.items.map((c) => (
                  <tr key={c.id}>
                    <td className="whitespace-nowrap px-2 py-1.5">{new Date(c.at).toLocaleString()}</td>
                    <td className="px-2 py-1.5">
                      {c.step}
                      {c.attempt > 1 ? ` (intento ${c.attempt})` : ''}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 font-mono text-[11px]">
                      {c.model} · {c.effort}
                    </td>
                    <td className="px-2 py-1.5" title={c.error ?? ''}>
                      {c.status === 'ok' ? 'correcta' : c.status === 'cancelled' ? 'cancelada' : c.status === 'invalid' ? 'inválida' : 'error'}
                    </td>
                    <td className="px-2 py-1.5 tabular">{n((c.input_tokens ?? 0) + (c.cache_creation_tokens ?? 0) + (c.cache_read_tokens ?? 0) || null)}</td>
                    <td className="px-2 py-1.5 tabular">{n(c.output_tokens)}</td>
                    <td className="px-2 py-1.5 tabular">{c.cache_read_tokens ? `${n(c.cache_read_tokens)} leídos` : '—'}</td>
                    <td className="px-2 py-1.5 tabular">{c.duration_ms ? `${(c.duration_ms / 1000).toFixed(1)} s` : '—'}</td>
                    <td className="px-2 py-1.5">{c.sent?.frame_count !== undefined ? `${c.sent.frame_count} fotogramas` : '—'}</td>
                    <td className="px-2 py-1.5 tabular">{c.cost_estimate_usd !== null ? `≈ ${c.cost_estimate_usd.toFixed(3)} USD` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Dialog>
  )
}
