import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  BadgeCheck,
  ChartNoAxesColumn,
  CircleAlert,
  Clapperboard,
  Ellipsis,
  History,
  LayoutGrid,
  Redo2,
  RefreshCw,
  Sparkles,
  Undo2,
  Wand,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Badge, EmptyState, ProgressBar, Spinner } from '@/components/ui/feedback'
import { Select } from '@/components/ui/fields'
import { Menu } from '@/components/ui/Menu'
import { BudgetDeclined, useBudget } from '@/hooks/budget-context'
import { keys, useClaudeStatus } from '@/hooks/queries'
import { ApiError, api } from '@/lib/api'
import { formatRelative, STYLE_META } from '@/lib/format'
import { PLAN_STATUS_TONE, POLICY, SCENE_KIND, TYPE_META, fmtT } from '@/lib/plan'
import type { Asset, InterventionStatus, InterventionType, PlanState, StyleId } from '@/lib/types'
import { AnimationsSection } from './AnimationsSection'
import { InterventionCard } from './InterventionCard'
import { StoryboardDialog, UsageDialog, VersionsDialog } from './PlanDialogs'

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err))

function Section({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="group rounded-xl border border-line bg-surface-2">
      <summary className="cursor-pointer list-none px-3 py-2 text-[12px] font-semibold uppercase tracking-wider text-fg-faint group-open:border-b group-open:border-line">
        {title}
      </summary>
      <div className="space-y-2 px-3 py-2.5 text-[12.5px] leading-relaxed text-fg-muted">{children}</div>
    </details>
  )
}

export function PlanPanel({
  projectId,
  asset,
  state,
  styleId,
  analyzed,
  selected,
  onSelect,
  onSeek,
  onOpenScene,
}: {
  projectId: string
  asset: Asset
  state: PlanState | undefined
  styleId: StyleId
  analyzed: boolean
  selected: string | null
  onSelect: (id: string | null) => void
  onSeek: (t: number) => void
  onOpenScene?: (iid: string) => void
}) {
  const qc = useQueryClient()
  const claude = useClaudeStatus()
  const budget = useBudget()
  const [style, setStyle] = useState<StyleId>(styleId)
  const [instruction, setInstruction] = useState('')
  const [globalInstruction, setGlobalInstruction] = useState('')
  const [pending, setPending] = useState(false)
  const [storyboard, setStoryboard] = useState(false)
  const [versions, setVersions] = useState(false)
  const [usage, setUsage] = useState(false)
  const plan = state?.plan ?? null
  const job = state?.job ?? null
  const busy = pending || Boolean(job)
  const aspect = asset.display_width / asset.display_height

  const apply = (data: PlanState) => {
    qc.setQueryData(keys.plan(projectId), data)
    qc.invalidateQueries({ queryKey: keys.planVersions(projectId) })
  }
  const run = async (fn: () => Promise<PlanState | unknown>, ok?: string): Promise<boolean> => {
    setPending(true)
    try {
      const r = await fn()
      if (r && typeof r === 'object' && 'labels' in (r as object)) apply(r as PlanState)
      else qc.invalidateQueries({ queryKey: keys.plan(projectId) })
      qc.invalidateQueries({ queryKey: keys.jobs })
      if (ok) toast.success(ok)
      return true
    } catch (err) {
      if (err instanceof BudgetDeclined) toast.info(err.message)
      else toast.error('No se pudo completar', { description: errorText(err) })
      return false
    } finally {
      setPending(false)
    }
  }

  const generate = () =>
    run(
      () => budget((c) => api.generatePlan(projectId, { style, instruction: instruction.trim() || null, confirm_budget: c })),
      'Claude está planificando la edición',
    )
  const revise = (text: string, scope: string[]) =>
    run(() => budget((c) => api.revisePlan(projectId, { instruction: text, scope, confirm_budget: c })), 'Corrección enviada a Claude')
  const setStatus = (id: string, s: InterventionStatus) => run(() => api.patchIntervention(projectId, id, { status: s }))
  const setType = async (id: string, t: InterventionType) => {
    await run(() => api.patchIntervention(projectId, id, { type: t }))
    toast.info(`Tipo cambiado a «${TYPE_META[t].label}»`, {
      description: 'La propuesta queda marcada para revisar. ¿Quieres que Claude adapte el diseño al nuevo tipo?',
      action: { label: 'Adaptar con Claude', onClick: () => void revise(`Convierte esta intervención en «${TYPE_META[t].label}» y adapta su diseño, elementos y movimiento a ese tipo.`, [id]) },
      duration: 10_000,
    })
  }

  // Si la intervención seleccionada desaparece (corrección, deshacer…), se deselecciona.
  const ids = plan?.document.interventions.map((i) => i.id).join('|') ?? ''
  useEffect(() => {
    if (selected && !ids.split('|').includes(selected)) onSelect(null)
  }, [ids, selected, onSelect])

  const groups = useMemo(() => {
    if (!plan) return []
    const scenes = plan.document.understanding.scenes
    const out = new Map<number, typeof plan.document.interventions>()
    for (const i of plan.document.interventions) {
      const key = i.scene_indices[0] ?? 0
      out.set(key, [...(out.get(key) ?? []), i])
    }
    return [...out.entries()].sort((a, b) => a[0] - b[0]).map(([scene, items]) => ({ scene, reading: scenes.find((s) => s.scene_index === scene), items }))
  }, [plan])

  // ---- Sin plan ---------------------------------------------------------------
  const notReady = claude.data && !claude.data.ready
  const starter = (
    <div className="space-y-3 rounded-xl border border-line bg-surface-2 p-3.5">
      <div className="flex items-center gap-2">
        <Select<StyleId>
          label="Estilo del plan"
          className="flex-1"
          value={style}
          onValueChange={setStyle}
          options={(Object.keys(STYLE_META) as StyleId[]).map((s) => ({ value: s, label: STYLE_META[s].name }))}
        />
      </div>
      <textarea
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        rows={2}
        placeholder="Indicaciones opcionales para Claude (p. ej. «público de negocio, que no sea recargado»)"
        className="w-full resize-none rounded-lg border border-line-strong bg-surface-1 p-2 text-[12.5px] text-fg placeholder:text-fg-faint focus:border-accent focus:outline-none"
        aria-label="Indicaciones para Claude"
      />
      <Button className="w-full" variant="primary" icon={<Sparkles className="size-4" />} loading={pending} disabled={busy || !analyzed || Boolean(notReady)} onClick={() => void generate()}>
        {plan ? 'Generar una propuesta nueva' : 'Planificar edición con IA'}
      </Button>
      {!analyzed && <p className="text-xs text-warning">Primero analiza el video: la planificación usa la transcripción, las escenas y los fotogramas.</p>}
      {notReady && (
        <div className="rounded-lg bg-warning/10 px-3 py-2 text-xs leading-relaxed text-fg-muted">
          <p className="font-medium text-warning">Claude no está conectado (opcional).</p>
          <p className="mt-1">
            <span className="text-fg">Disponible sin conexión:</span> importar, transcribir, revisar la transcripción, subtítulos y su estilo, presets, ajustes de audio y exportar.
          </p>
          <p className="mt-1">
            <span className="text-fg">Necesita tu clave de API de Anthropic:</span> el plan de edición y las animaciones que dirige Claude. Se factura en tu cuenta de Anthropic; no está incluido en Claude Pro ni Max.{' '}
            <Link to="/settings#claude" className="text-accent underline">
              Configurar en Ajustes → Claude
            </Link>
          </p>
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-fg-faint">
        Se envían a Claude Opus 5.5 la transcripción con tiempos, los datos de escenas y rostros, tus preferencias y unos pocos fotogramas reducidos; nunca el archivo de video.
      </p>
    </div>
  )

  return (
    <div className="space-y-3 p-4">
      {job && (
        <div className="rounded-xl border border-accent/30 bg-accent-soft/40 p-3.5" role="status" aria-live="polite">
          <div className="mb-1.5 flex items-center gap-2 text-[13px] font-medium text-fg">
            <Spinner className="size-3.5" />
            {job.stage ?? job.label}
            <span className="ml-auto tabular text-xs text-fg-muted">{Math.round(job.progress * 100)} %</span>
          </div>
          <ProgressBar value={job.progress} label="Progreso de la planificación" />
          <div className="mt-2 flex items-center justify-between text-[11px] text-fg-faint">
            <span>Iniciado {formatRelative(job.started_at ?? job.created_at)} · Claude Opus 5.5</span>
            <Button size="sm" variant="ghost" className="h-7" onClick={() => void run(() => api.cancelJob(job.id), 'Solicitud cancelada')}>
              Cancelar
            </Button>
          </div>
        </div>
      )}

      {!plan && !job && (
        <>
          <EmptyState icon={<Wand className="size-5" />} title="Sin plan de edición" description="Claude Opus 5.5 analizará qué se dice y qué se ve en cada momento y propondrá intervenciones concretas que podrás revisar, corregir y aprobar." />
          {starter}
        </>
      )}

      {state?.sessions[0]?.status === 'failed' && !job && (
        <p className="rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
          La última solicitud falló: {state.sessions[0].error}
        </p>
      )}

      {plan && (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={PLAN_STATUS_TONE[plan.status]}>{plan.status_label}</Badge>
            <span className="text-xs text-fg-muted">
              v{plan.current_version} · {STYLE_META[plan.document.style].name}
            </span>
            {plan.approved_version && plan.status !== 'approved' && <Badge>Aprobada: v{plan.approved_version}</Badge>}
            <div className="ml-auto flex items-center">
              <Button size="icon-sm" variant="ghost" aria-label="Deshacer" title="Deshacer" disabled={busy || !plan.can_undo} onClick={() => void run(() => api.undoPlan(projectId))}>
                <Undo2 className="size-4" />
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label="Rehacer" title="Rehacer" disabled={busy || !plan.can_redo} onClick={() => void run(() => api.redoPlan(projectId))}>
                <Redo2 className="size-4" />
              </Button>
              <Button size="icon-sm" variant="ghost" aria-label="Storyboard" title="Storyboard" onClick={() => setStoryboard(true)}>
                <LayoutGrid className="size-4" />
              </Button>
              <Menu
                items={[
                  { label: 'Historial de versiones', icon: <History />, onSelect: () => setVersions(true) },
                  { label: 'Consumo de Claude', icon: <ChartNoAxesColumn />, onSelect: () => setUsage(true) },
                  { label: 'Marcar «Requiere corrección»', onSelect: () => void run(() => api.planStatus(projectId, 'needs_changes')), separatorBefore: true },
                  { label: 'Rechazar el plan', danger: true, onSelect: () => void run(() => api.planStatus(projectId, 'rejected', 'Rechazado por el usuario')) },
                ]}
                trigger={
                  <Button size="icon-sm" variant="ghost" aria-label="Más acciones del plan">
                    <Ellipsis className="size-4" />
                  </Button>
                }
              />
            </div>
          </div>
          <p className="text-[11.5px] leading-snug text-fg-faint">{plan.version.summary}</p>

          {plan.staleness.stale && (
            <div className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning">
              <div className="flex items-center gap-1.5 font-semibold">
                <CircleAlert className="size-3.5" />
                {Object.keys(plan.staleness.affected).length} intervención(es) pueden haber quedado obsoletas
              </div>
              <p className="mt-1 leading-relaxed">
                {plan.staleness.asset_changed ? 'El video base cambió. ' : ''}
                {plan.staleness.transcript_changed ? 'La transcripción cambió después de planificar. ' : ''}
                {plan.staleness.analysis_changed ? 'El análisis de escenas se repitió. ' : ''}
                Las versiones anteriores se conservan.
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} disabled={busy} onClick={() => void run(() => api.refreshPlan(projectId), 'Tiempos recalculados')}>
                  Recalcular tiempos
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<Sparkles className="size-3.5" />}
                  disabled={busy}
                  onClick={() => void revise('La transcripción o el análisis cambiaron: revisa estas intervenciones para que sigan siendo coherentes con lo que se dice y se ve ahora.', Object.keys(plan.staleness.affected))}
                >
                  Revisar afectadas con IA
                </Button>
              </div>
            </div>
          )}

          <Section title="Propuesta general" defaultOpen>
            <p className="text-fg">{plan.document.understanding.summary}</p>
            <p>
              <span className="font-semibold text-fg">Intención:</span> {plan.document.understanding.intent}
            </p>
            <p>
              <span className="font-semibold text-fg">Concepto visual:</span> {plan.document.direction.concept}
            </p>
            <p>
              <span className="font-semibold text-fg">Ritmo:</span> {plan.document.direction.pacing}
            </p>
            {plan.document.understanding.structure.length > 0 && (
              <ol className="space-y-0.5">
                {plan.document.understanding.structure.map((s) => (
                  <li key={s.start}>
                    <button type="button" className="font-mono text-[11px] text-accent hover:underline" onClick={() => onSeek(s.start)}>
                      {fmtT(s.start)}
                    </button>{' '}
                    <span className="text-fg">{s.label}</span> — {s.purpose}
                  </li>
                ))}
              </ol>
            )}
          </Section>
          <Section title="Dirección creativa y lectura del video">
            <p>
              <span className="font-semibold text-fg">Lenguaje visual:</span> {plan.document.direction.visual_language}
            </p>
            <p>
              <span className="font-semibold text-fg">Tipografía:</span> {plan.document.direction.typography}
            </p>
            <p>
              <span className="font-semibold text-fg">Color:</span> {plan.document.direction.color_usage}
            </p>
            <p>
              <span className="font-semibold text-fg">Densidad:</span> {plan.document.direction.density}
              {plan.document.validation.density_per_minute !== undefined &&
                ` (medida: ${plan.document.validation.density_per_minute}/min; preferencia ≈ ${plan.document.validation.density_target}/min)`}
            </p>
            {plan.document.understanding.scenes.map((s) => (
              <p key={s.scene_index}>
                <span className="font-semibold text-fg">Escena {s.scene_index + 1}:</span> {SCENE_KIND[s.kind] ?? s.kind} · {POLICY[s.policy]} — {s.observed}
              </p>
            ))}
            <div className="grid grid-cols-1 gap-2">
              <div>
                <div className="font-semibold text-fg">Hechos observados</div>
                <ul className="list-disc pl-4">{plan.document.understanding.observed_facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
              </div>
              <div>
                <div className="font-semibold text-fg">Inferencias del modelo</div>
                <ul className="list-disc pl-4">{plan.document.understanding.inferences.map((f, i) => <li key={i}>{f}</li>)}</ul>
              </div>
            </div>
          </Section>

          {(plan.document.validation.conflicts?.length ?? 0) > 0 && (
            <div className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning">
              <div className="font-semibold">Conflictos detectados</div>
              <ul className="mt-1 list-disc pl-4">
                {plan.document.validation.conflicts!.map((c) => (
                  <li key={`${c.a}-${c.b}`}>
                    {c.reason} ({c.seconds} s)
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="rounded-xl border border-line bg-surface-2 p-2.5">
            <div className="flex gap-1.5">
              <textarea
                value={globalInstruction}
                onChange={(e) => setGlobalInstruction(e.target.value)}
                rows={2}
                placeholder={selected ? 'Pide cambios para la intervención seleccionada…' : 'Pide cambios para todo el plan (p. ej. «menos animaciones al principio»)…'}
                className="min-w-0 flex-1 resize-none rounded-lg border border-line-strong bg-surface-1 p-2 text-[12.5px] text-fg placeholder:text-fg-faint focus:border-accent focus:outline-none"
                aria-label="Instrucción para Claude"
              />
              <Button
                size="icon"
                variant="primary"
                aria-label="Enviar instrucción a Claude"
                disabled={busy || globalInstruction.trim().length < 2}
                onClick={async () => {
                  if (await revise(globalInstruction.trim(), selected ? [selected] : [])) setGlobalInstruction('')
                }}
              >
                <Sparkles className="size-4" />
              </Button>
            </div>
            <p className="mt-1 text-[11px] text-fg-faint">
              {selected ? 'Ámbito: solo la intervención seleccionada.' : 'Ámbito: todo el plan. Claude devuelve solo los cambios necesarios.'}
            </p>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-fg-faint">
              {plan.document.interventions.length} intervenciones
            </span>
            <Button size="sm" variant="ghost" className="ml-auto h-7" disabled={busy} onClick={() => void run(() => api.bulkPlan(projectId, 'accepted'))}>
              Aceptar pendientes
            </Button>
            <Button size="sm" variant="ghost" className="h-7" disabled={busy} onClick={() => void run(() => api.bulkPlan(projectId, 'rejected'))}>
              Rechazar pendientes
            </Button>
          </div>

          {groups.map((g) => (
            <section key={g.scene} aria-label={`Escena ${g.scene + 1}`}>
              <h3 className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-semibold text-fg-muted">
                <Clapperboard className="size-3.5" /> Escena {g.scene + 1}
                {g.reading && <span className="font-normal text-fg-faint">· {SCENE_KIND[g.reading.kind] ?? g.reading.kind}</span>}
              </h3>
              <ol className="space-y-2">
                {g.items.map((i) => (
                  <InterventionCard
                    key={i.id}
                    item={i}
                    index={plan.document.interventions.indexOf(i)}
                    frames={state?.frames ?? {}}
                    aspect={aspect}
                    selected={selected === i.id}
                    busy={busy}
                    onSelect={() => onSelect(selected === i.id ? null : i.id)}
                    onSeek={onSeek}
                    onStatus={(s) => void setStatus(i.id, s)}
                    onType={(t) => void setType(i.id, t)}
                    onAlternative={(text) => void run(() => budget((c) => api.alternative(projectId, i.id, text, c)), 'Claude está preparando una alternativa')}
                    onRevise={(text) => revise(text, [i.id])}
                  />
                ))}
              </ol>
            </section>
          ))}

          <div className="rounded-xl border border-line bg-surface-2 p-3">
            {plan.status === 'approved' ? (
              <div className="flex items-start gap-2 text-[13px] text-success">
                <BadgeCheck className="mt-0.5 size-4 shrink-0" />
                <div>
                  Plan aprobado (v{plan.approved_version}). Versión inmutable lista para el motor de animaciones de la Fase 4.
                  <a href={`/api/projects/${projectId}/plan/approved`} target="_blank" rel="noreferrer" className="mt-1 block text-xs text-accent underline">
                    Ver contrato aprobado (JSON)
                  </a>
                </div>
              </div>
            ) : (
              <>
                {plan.approval_problems.length > 0 && (
                  <ul className="mb-2 list-disc pl-4 text-xs text-fg-muted">
                    {plan.approval_problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )}
                <Button className="w-full" variant="primary" icon={<BadgeCheck className="size-4" />} disabled={busy || plan.approval_problems.length > 0} onClick={() => void run(() => api.approvePlan(projectId), 'Plan aprobado')}>
                  Aprobar plan completo
                </Button>
              </>
            )}
          </div>

          {plan.approved_version !== null && (
            <AnimationsSection projectId={projectId} asset={asset} approvedVersion={plan.approved_version} onSeek={onSeek} onOpenScene={onOpenScene} />
          )}

          <details className="rounded-xl border border-line">
            <summary className="cursor-pointer px-3 py-2 text-[12px] font-semibold text-fg-muted">Nueva propuesta desde cero</summary>
            <div className="p-2.5">{starter}</div>
          </details>
        </>
      )}

      {plan && (
        <>
          <StoryboardDialog open={storyboard} onOpenChange={setStoryboard} doc={plan.document} frames={state?.frames ?? {}} aspect={aspect} onSeek={onSeek} />
          <VersionsDialog open={versions} onOpenChange={setVersions} projectId={projectId} busy={busy} onRestore={(n) => void run(() => api.restorePlan(projectId, n), `Versión ${n} restaurada`)} />
        </>
      )}
      <UsageDialog open={usage} onOpenChange={setUsage} projectId={projectId} />
    </div>
  )
}
